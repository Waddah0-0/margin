"""Clone a public GitHub repository into a temporary workspace.

Security posture: only ``https://github.com/<owner>/<repo>`` URLs are accepted by default,
submodules are not fetched, symlinks are checked out as plain files, all credential prompts
are disabled, and the clone is size- and time-limited. Repository code is never executed.

Before cloning, the repository size reported by the GitHub API is checked against the limit,
so oversized repositories are refused without downloading them. If the API cannot be reached
(offline, rate-limited), the clone goes ahead with a warning and the post-clone check and
timeout still apply. ``GITHUB_TOKEN`` is only used for that API call (higher rate limits);
it is never given to ``git``.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import tempfile
from collections.abc import Sequence
from pathlib import Path

import httpx

from margin_core._fs import directory_size, force_rmtree
from margin_core.config import get_settings
from margin_core.errors import InvalidTargetError, LimitExceededError, LoaderError
from margin_core.loaders.base import Loader, LoaderLimits, Workspace
from margin_core.loaders.filters import FilterConfig
from margin_core.loaders.git import git_available, git_command, safe_git_env
from margin_core.loaders.local import LocalLoader

GITHUB_URL_RE = re.compile(
    r"^https://github\.com/"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/"
    r"(?P<repo>[A-Za-z0-9._-]{1,100}?)"
    r"(?:\.git)?/?$"
)
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
GITHUB_API = "https://api.github.com"


def parse_github_url(url: str) -> tuple[str, str]:
    """Return ``(owner, repo)`` for a valid GitHub repository URL."""
    match = GITHUB_URL_RE.match(url.strip())
    if not match or match.group("repo") in {".", ".."}:
        raise InvalidTargetError(
            f"Not a GitHub repository URL: {url!r} (expected https://github.com/<owner>/<repo>)"
        )
    return match.group("owner"), match.group("repo")


class GitHubLoader(Loader):
    """Loads ``https://github.com/<owner>/<repo>`` via a blobless clone.

    ``--filter=blob:none`` downloads full commit history cheaply; only the blobs needed
    for the checked-out tree are fetched.
    """

    def __init__(
        self,
        limits: LoaderLimits | None = None,
        filters: FilterConfig | None = None,
        *,
        allow_non_github_urls: bool = False,
        api_base: str = GITHUB_API,
        github_token: str | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.limits = limits or LoaderLimits()
        self.filters = filters or FilterConfig()
        self.allow_non_github_urls = allow_non_github_urls  # tests only (file:// fixtures)
        self.api_base = api_base.rstrip("/")
        if github_token is None:
            secret = get_settings().github_token  # GITHUB_TOKEN env var or MARGIN_ENV_FILE
            github_token = secret.get_secret_value() if secret else None
        self.github_token = github_token or None
        self._http_client = http_client

    @staticmethod
    def can_handle(target: str) -> bool:
        return target.strip().lower().startswith("https://github.com/")

    def _validate(self, target: str, branch: str | None) -> str:
        if branch is not None and (not BRANCH_RE.match(branch) or branch.startswith("-")):
            raise InvalidTargetError(f"Invalid branch name: {branch!r}")
        if self.allow_non_github_urls:
            return target
        owner, repo = parse_github_url(target)
        return f"https://github.com/{owner}/{repo}.git"

    async def check_remote_size(self, owner: str, repo: str) -> str | None:
        """Refuse repositories GitHub reports as too large.

        Returns a warning when the check could not be done; raises
        :class:`LimitExceededError` when the repository is over the limit and
        :class:`InvalidTargetError` when it does not exist (or is private).
        """
        url = f"{self.api_base}/repos/{owner}/{repo}"
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.github_token:
            headers["Authorization"] = f"Bearer {self.github_token}"
        try:
            if self._http_client is not None:
                response = await self._http_client.get(url, headers=headers, timeout=10.0)
            else:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            return f"Could not check the repository size before cloning ({type(exc).__name__})"
        if response.status_code == 404:
            raise InvalidTargetError(
                f"GitHub repository {owner}/{repo} was not found. It may be private; "
                "private repositories are not supported."
            )
        if response.status_code != 200:
            return (
                "Could not check the repository size before cloning "
                f"(GitHub API returned HTTP {response.status_code})"
            )
        try:
            size_kb = response.json().get("size")
        except ValueError:
            return "Could not check the repository size before cloning (invalid API response)"
        if isinstance(size_kb, int) and size_kb * 1024 > self.limits.max_repo_size_bytes:
            raise LimitExceededError(
                f"Repository is about {size_kb * 1024} bytes according to GitHub, above the "
                f"{self.limits.max_repo_size_bytes} byte limit"
            )
        return None

    def _clone_command(self, url: str, dest: Path, branch: str | None) -> list[str]:
        args = [
            "-c",
            "core.symlinks=false",
            "-c",
            "credential.helper=",
            "clone",
            "--quiet",
            "--filter=blob:none",
            "--single-branch",
            "--no-recurse-submodules",
        ]
        if branch:
            args += ["--branch", branch]
        return git_command([*args, "--", url, str(dest)])

    async def _clone(self, url: str, dest: Path, branch: str | None) -> None:
        """Clone as a child process we can kill. If the run is cancelled or the clone times
        out, git is stopped and waited for before anything is deleted, so a half-written clone
        never outlives the run."""
        proc = await asyncio.create_subprocess_exec(
            *self._clone_command(url, dest, branch),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
            env=safe_git_env(),
        )
        try:
            _, stderr = await asyncio.wait_for(proc.communicate(), self.limits.clone_timeout_s)
        except TimeoutError as exc:
            await _stop(proc)
            raise LimitExceededError(
                f"Clone timed out after {self.limits.clone_timeout_s:.0f}s"
            ) from exc
        except BaseException:  # cancelled
            await _stop(proc)
            raise
        if proc.returncode != 0:
            message = stderr.decode("utf-8", errors="replace").strip()
            raise LoaderError(f"Could not clone {url}: {message}")

    async def load(
        self,
        target: str,
        *,
        paths: Sequence[str] | None = None,
        branch: str | None = None,
    ) -> Workspace:
        if not git_available():
            raise LoaderError("git is not installed or not on PATH")
        url = self._validate(target, branch)
        size_warning: str | None = None
        if not self.allow_non_github_urls:
            size_warning = await self.check_remote_size(*parse_github_url(target))
        tmp = Path(tempfile.mkdtemp(prefix="margin-"))
        try:
            dest = tmp / "repo"
            await self._clone(url, dest, branch)
            size = await asyncio.to_thread(directory_size, dest)
            if size > self.limits.max_repo_size_bytes:
                raise LimitExceededError(
                    f"Repository is {size} bytes, above the {self.limits.max_repo_size_bytes} limit"
                )
            local = LocalLoader(self.limits, self.filters)
            ws = await asyncio.to_thread(local.load_sync, str(dest), paths=paths, source=target)
        except BaseException:
            force_rmtree(tmp)
            raise
        ws.add_cleanup(lambda: force_rmtree(tmp))
        if size_warning:
            ws.warnings.append(size_warning)
        return ws


async def _stop(proc: asyncio.subprocess.Process) -> None:
    """Kill a child process and wait until it has really exited."""
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await asyncio.shield(proc.wait())
