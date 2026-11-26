"""Check GitHub Releases for newer margin versions and download verified Windows installers."""

from __future__ import annotations

import hashlib
import os
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

from margin_api import __version__

DEFAULT_UPDATE_REPO = "Waddah0-0/margin"
CACHE_TTL_S = 900.0  # 15 minutes
MAX_NOTES_CHARS = 2500
MAX_INSTALLER_BYTES = 500_000_000  # 500 MB safety ceiling
ALLOWED_DOWNLOAD_HOSTS = frozenset(
    {
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)

_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-.]?(a|alpha|b|beta|rc)\.?(\d+))?$", re.I)
_PRE_ORDER = {"a": 0, "alpha": 0, "b": 1, "beta": 1, "rc": 2}


class UpdateStatus(BaseModel):
    current_version: str
    latest_version: str | None = None
    update_available: bool = False
    release_url: str | None = None
    download_url: str | None = None
    checksum_url: str | None = None
    asset_name: str | None = None
    release_notes: str | None = None
    published_at: str | None = None
    can_install: bool = Field(
        default=False,
        description="True when running in the desktop app and a Windows installer asset is ready.",
    )


class UpdateInstallResult(BaseModel):
    status: Literal["started"] = "started"
    version: str
    installer_path: str


def parse_version(raw: str) -> tuple[int, int, int, int, int] | None:
    """Parse ``v0.1.5`` or ``0.1.5rc1`` into a comparable tuple (final > prerelease)."""
    match = _VERSION_RE.match(raw.strip())
    if not match:
        return None
    major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
    pre_kind = match.group(4)
    if pre_kind is None:
        return (major, minor, patch, 1, 0)
    pre_num = int(match.group(5) or 0)
    return (major, minor, patch, 0, _PRE_ORDER[pre_kind.lower()] * 1000 + pre_num)


def is_newer(latest: str, current: str) -> bool:
    """Return True only when ``latest`` is strictly newer than ``current``."""
    a = parse_version(latest)
    b = parse_version(current)
    if a is None or b is None:
        return False
    return a > b


def validate_download_url(url: str) -> str:
    """Only permit HTTPS downloads from GitHub's release domains."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in ALLOWED_DOWNLOAD_HOSTS:
        raise ValueError(f"Refusing untrusted update URL: {url}")
    return url


def _pick_windows_assets(
    assets: list[dict[str, Any]],
) -> tuple[str | None, str | None, str | None]:
    """Return ``(asset_name, download_url, checksum_url)`` for a Windows setup executable."""
    installer_name: str | None = None
    installer_url: str | None = None
    checksum_url: str | None = None

    for asset in assets:
        name = str(asset.get("name") or "")
        url = str(asset.get("browser_download_url") or "")
        lower = name.lower()
        if lower.startswith("margin-setup-") and lower.endswith(".exe") and url:
            installer_name = name
            installer_url = url
            break

    if installer_name:
        wanted_sha = f"{installer_name.lower()}.sha256"
        for asset in assets:
            name = str(asset.get("name") or "")
            url = str(asset.get("browser_download_url") or "")
            if name.lower() == wanted_sha and url:
                checksum_url = url
                break

    return installer_name, installer_url, checksum_url


def _clean_notes(body: str | None) -> str | None:
    if not body:
        return None
    text = body.strip()
    if not text:
        return None
    if len(text) > MAX_NOTES_CHARS:
        text = text[: MAX_NOTES_CHARS - 1].rstrip() + "…"
    return text


def _fetch_latest_github_release(repo: str) -> dict[str, Any]:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"margin/{__version__}",
    }
    with httpx.Client(timeout=5.0, follow_redirects=True) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Unexpected GitHub release payload")
        return payload


class UpdateChecker:
    """Checks GitHub Releases with an in-memory cache so UI polling never spams the API."""

    def __init__(
        self,
        *,
        current_version: str = __version__,
        repo: str | None = None,
        fetcher: Callable[[str], dict[str, Any]] | None = None,
        ttl_s: float = CACHE_TTL_S,
    ) -> None:
        self.current_version = current_version
        self.repo = repo or os.environ.get("MARGIN_UPDATE_REPO") or DEFAULT_UPDATE_REPO
        self._custom_fetcher = fetcher is not None
        self._fetcher = fetcher or _fetch_latest_github_release
        self._ttl_s = ttl_s
        self._cached: UpdateStatus | None = None
        self._cached_at: float = 0.0

    def check(self, *, force: bool = False, can_install: bool = False) -> UpdateStatus:
        if not self._custom_fetcher and os.environ.get("MARGIN_DISABLE_UPDATE_CHECK") == "1":
            return UpdateStatus(current_version=self.current_version, can_install=False)

        now = time.monotonic()
        if not force and self._cached is not None and (now - self._cached_at) < self._ttl_s:
            return self._cached.model_copy(
                update={"can_install": can_install and bool(self._cached.download_url)}
            )

        try:
            payload = self._fetcher(self.repo)
        except Exception:  # noqa: BLE001 - offline or rate-limited: fail quietly
            fallback = UpdateStatus(current_version=self.current_version)
            self._cached = fallback
            self._cached_at = now
            return fallback

        tag = str(payload.get("tag_name") or "").strip()
        latest = tag.lstrip("vV") or None
        available = bool(latest and is_newer(latest, self.current_version))
        assets = payload.get("assets")
        asset_list = assets if isinstance(assets, list) else []
        asset_name, download_url, checksum_url = _pick_windows_assets(asset_list)

        status = UpdateStatus(
            current_version=self.current_version,
            latest_version=latest,
            update_available=available,
            release_url=str(payload.get("html_url") or "") or None,
            download_url=download_url,
            checksum_url=checksum_url,
            asset_name=asset_name,
            release_notes=_clean_notes(
                payload.get("body") if isinstance(payload.get("body"), str) else None
            ),
            published_at=str(payload.get("published_at") or "") or None,
            can_install=can_install and available and bool(download_url),
        )
        self._cached = status
        self._cached_at = now
        return status


def _expected_sha256(checksum_url: str) -> str:
    validate_download_url(checksum_url)
    with httpx.Client(timeout=15.0, follow_redirects=True) as client:
        resp = client.get(checksum_url, headers={"User-Agent": f"margin/{__version__}"})
        resp.raise_for_status()
        validate_download_url(str(resp.url))
        first_token = resp.text.strip().split()[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", first_token):
        raise ValueError("Invalid SHA-256 checksum file on release")
    return first_token


def download_installer(status: UpdateStatus, dest_dir: Path) -> Path:
    """Download the verified Windows installer into ``dest_dir`` and return its path."""
    if not status.download_url or not status.asset_name:
        raise ValueError("No Windows installer asset is attached to this release")
    url = validate_download_url(status.download_url)
    safe_filename = Path(status.asset_name).name
    if not safe_filename.lower().endswith(".exe"):
        raise ValueError(f"Unexpected installer filename: {safe_filename}")

    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / safe_filename
    part = dest_dir / f"{safe_filename}.part"
    digest = hashlib.sha256()
    total = 0

    try:
        with httpx.Client(timeout=120.0, follow_redirects=True) as client:
            with client.stream(
                "GET", url, headers={"User-Agent": f"margin/{__version__}"}
            ) as response:
                response.raise_for_status()
                validate_download_url(str(response.url))
                with part.open("wb") as out:
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > MAX_INSTALLER_BYTES:
                            raise ValueError("Installer download exceeded size limit")
                        digest.update(chunk)
                        out.write(chunk)
        if total == 0:
            raise ValueError("Downloaded installer file is empty")
        if status.checksum_url:
            expected = _expected_sha256(status.checksum_url)
            actual = digest.hexdigest().lower()
            if actual != expected:
                raise ValueError("Installer SHA-256 checksum mismatch")
        part.replace(target)
    except BaseException:
        part.unlink(missing_ok=True)
        raise

    return target
