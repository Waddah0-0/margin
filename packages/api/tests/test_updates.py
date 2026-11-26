"""Tests for GitHub Releases update checks, download verification, and /updates endpoints."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from margin_api.app import create_app
from margin_api.updates import (
    UpdateChecker,
    UpdateStatus,
    download_installer,
    is_newer,
    validate_download_url,
)
from margin_core import AgentRegistry


def test_version_comparison() -> None:
    assert is_newer("0.1.5", "0.1.3")
    assert is_newer("v0.2.0", "0.1.9")
    assert is_newer("0.1.5", "0.1.5rc1")
    assert not is_newer("0.1.3", "0.1.3")
    assert not is_newer("0.1.2", "0.1.3")
    assert not is_newer("not-a-version", "0.1.3")


def test_validate_download_url_allows_only_github_https() -> None:
    ok = "https://github.com/Waddah0-0/margin/releases/download/v0.1.5/margin-setup-0.1.5.exe"
    assert validate_download_url(ok) == ok
    with pytest.raises(ValueError):
        validate_download_url("http://github.com/Waddah0-0/margin/file.exe")
    with pytest.raises(ValueError):
        validate_download_url("https://evil.example.com/margin-setup-0.1.5.exe")


def test_updates_endpoint_reports_release_notes_and_caches() -> None:
    calls = 0

    def fake_fetch(_repo: str) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {
            "tag_name": "v0.2.0",
            "html_url": "https://github.com/Waddah0-0/margin/releases/tag/v0.2.0",
            "published_at": "2026-11-27T00:00:00Z",
            "body": "## Highlights\n- Deep black dark mode\n- Auto-updater",
            "assets": [
                {
                    "name": "margin-setup-0.2.0.exe",
                    "browser_download_url": (
                        "https://github.com/Waddah0-0/margin/releases/download/"
                        "v0.2.0/margin-setup-0.2.0.exe"
                    ),
                },
                {
                    "name": "margin-setup-0.2.0.exe.sha256",
                    "browser_download_url": (
                        "https://github.com/Waddah0-0/margin/releases/download/"
                        "v0.2.0/margin-setup-0.2.0.exe.sha256"
                    ),
                },
            ],
        }

    checker = UpdateChecker(current_version="0.1.3", fetcher=fake_fetch)
    app = create_app(registry=AgentRegistry([]), llm_factory=None, update_checker=checker)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        first = client.get("/updates").json()
        second = client.get("/updates").json()
        assert calls == 1  # cached
        assert first == second
        assert first["update_available"] is True
        assert first["latest_version"] == "0.2.0"
        assert "Deep black dark mode" in first["release_notes"]
        assert first["asset_name"] == "margin-setup-0.2.0.exe"
        assert first["checksum_url"].endswith(".sha256")
        assert first["can_install"] is False  # no desktop callback registered

        forced = client.get("/updates?force=true").json()
        assert calls == 2
        assert forced["latest_version"] == "0.2.0"

        # Without desktop install callback, POST /updates/install returns 400
        refused = client.post("/updates/install")
        assert refused.status_code == 400


def test_download_installer_verifies_sha256_and_triggers_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = b"MZ-fake-inno-setup-binary"
    expected_sha = hashlib.sha256(payload).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(".sha256"):
            return httpx.Response(200, text=f"{expected_sha}  margin-setup-0.2.0.exe\n")
        return httpx.Response(200, content=payload)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def mock_client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr("margin_api.updates.httpx.Client", mock_client)

    status = UpdateStatus(
        current_version="0.1.3",
        latest_version="0.2.0",
        update_available=True,
        asset_name="margin-setup-0.2.0.exe",
        download_url="https://github.com/Waddah0-0/margin/releases/download/v0.2.0/margin-setup-0.2.0.exe",
        checksum_url="https://github.com/Waddah0-0/margin/releases/download/v0.2.0/margin-setup-0.2.0.exe.sha256",
        can_install=True,
    )
    saved = download_installer(status, tmp_path)
    assert saved.name == "margin-setup-0.2.0.exe"
    assert saved.read_bytes() == payload

    # Now verify POST /updates/install runs the desktop callback cleanly
    launched: list[Path] = []
    checker = UpdateChecker(
        current_version="0.1.3",
        fetcher=lambda _repo: {
            "tag_name": "v0.2.0",
            "html_url": "https://github.com/Waddah0-0/margin/releases/tag/v0.2.0",
            "assets": [
                {
                    "name": "margin-setup-0.2.0.exe",
                    "browser_download_url": status.download_url,
                },
                {
                    "name": "margin-setup-0.2.0.exe.sha256",
                    "browser_download_url": status.checksum_url,
                },
            ],
        },
    )
    app = create_app(
        registry=AgentRegistry([]),
        llm_factory=None,
        update_checker=checker,
        on_install_update=launched.append,
        updates_dir=tmp_path / "app-updates",
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        info = client.get("/updates").json()
        assert info["can_install"] is True
        res = client.post("/updates/install")
        assert res.status_code == 202, res.text
        assert res.json()["version"] == "0.2.0"
        assert len(launched) == 1
        assert launched[0].read_bytes() == payload
