"""The security guarantees, each shown by an attempt to break it.

- a folder we are pointed at cannot make git run its programs (config, hooks, LFS);
- files outside the workspace cannot be read, by path or through a symlink;
- cancelling a run during a clone stops git and leaves nothing behind;
- secrets (API keys, the GitHub token) never appear in logs or error messages.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from margin_core.errors import InvalidTargetError
from margin_core.loaders import load_workspace
from margin_core.loaders.base import Workspace
from margin_core.loaders.git import SAFE_GIT_CONFIG, GitCommandError, git_command, run_git
from margin_core.loaders.github import GitHubLoader
from margin_core.models import AgentResult, Evidence, Finding
from margin_core.reporting import to_json, to_markdown

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo, check=True, capture_output=True,
    )  # fmt: skip


def _trap(marker: Path) -> str:
    """A command that, if git ever runs it, leaves ``marker`` behind."""
    script = f"open({str(marker)!r}, 'w').write('ran')"
    return f'"{sys.executable}" -c "{script}"'.replace("\\", "/")


# ---- 1. untrusted repository config -------------------------------------------------------


@needs_git
async def test_a_repository_cannot_make_git_run_its_programs(tmp_path: Path) -> None:
    repo, marker = tmp_path / "hostile", tmp_path / "fsmonitor-ran"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    # the repository's own config names a program for git to run on index reads
    _git(repo, "config", "core.fsmonitor", _trap(marker))

    # sanity: the trap is armed. Plain git, as a careless tool would call it, runs it.
    subprocess.run(["git", "status"], cwd=repo, capture_output=True, check=False)  # noqa: ASYNC221
    if not marker.exists():
        pytest.skip("this git does not run core.fsmonitor here; nothing to prove")
    marker.unlink()

    async with await load_workspace(str(repo)) as ws:
        assert ws.git is not None
        await ws.git.commits(max_count=10)
        await ws.git.changed_files(max_count=10)
    run_git(["status"], cwd=repo)  # even an index-reading command, through margin's wrapper
    assert not marker.exists(), "margin let the repository run a program"


def _program(path: Path, marker: Path) -> str:
    """A script for settings git runs directly, without a shell: leaves ``marker`` behind."""
    path.write_text(f'#!/bin/sh\necho ran > "{marker.as_posix()}"\nexit 1\n', newline="\n")
    path.chmod(0o755)
    return path.as_posix()


def _commit_object(repo: Path, body: str) -> None:
    """Point HEAD at a hand-written commit (``body`` is everything after the parent line)."""
    parent = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    who = "t <t@example.com> 1700000000 +0000"
    sha = subprocess.run(
        ["git", "hash-object", "-t", "commit", "-w", "--stdin", "--literally"],
        cwd=repo, check=True, capture_output=True,
        input=body.format(parent=parent, who=who).encode(),
    ).stdout.decode().strip()  # fmt: skip
    _git(repo, "update-ref", "HEAD", sha)


def _hostile_repo(root: Path) -> Path:
    root.mkdir()
    _git(root, "init", "-q")
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    return root


async def _read_history(repo: Path) -> None:
    """All a run does with a folder's history; a failure is fine, a program running is not."""
    try:
        async with await load_workspace(str(repo)) as ws:
            assert ws.git is not None
            await ws.git.commits(max_count=10)
            await ws.git.changed_files(max_count=10)
    except GitCommandError:
        pass


@needs_git
async def test_a_signed_commit_cannot_make_git_log_run_a_program(tmp_path: Path) -> None:
    repo, marker = _hostile_repo(tmp_path / "hostile"), tmp_path / "gpg-ran"
    _commit_object(
        repo,
        f"tree {_tree(repo)}\nparent {{parent}}\nauthor {{who}}\ncommitter {{who}}\n"
        "gpgsig -----BEGIN PGP SIGNATURE-----\n \n abc\n -----END PGP SIGNATURE-----\n\n"
        "signed\n",
    )
    _git(repo, "config", "log.showSignature", "true")
    _git(repo, "config", "gpg.program", _program(tmp_path / "gpg.sh", marker))

    # sanity: plain git runs it
    subprocess.run(["git", "log", "--format=%H"], cwd=repo, capture_output=True, check=False)  # noqa: ASYNC221
    if not marker.exists():
        pytest.skip("this git does not run gpg.program here; nothing to prove")
    marker.unlink()

    await _read_history(repo)
    assert not marker.exists(), "margin let the repository run a program"


@needs_git
@pytest.mark.parametrize(
    "url", ["ssh://example.invalid/x.git", "{local}"], ids=["core.sshCommand", "uploadpack"]
)
async def test_a_missing_object_cannot_make_git_fetch_and_run_a_program(
    tmp_path: Path, url: str
) -> None:
    repo, marker = _hostile_repo(tmp_path / "hostile"), tmp_path / "fetch-ran"
    program = _program(tmp_path / "fetch.sh", marker)
    _git(repo, "config", "extensions.partialClone", "origin")
    _git(repo, "config", "remote.origin.promisor", "true")
    _git(repo, "config", "remote.origin.url", url.format(local=repo.as_posix()))
    _git(repo, "config", "core.sshCommand", program)
    _git(repo, "config", "remote.origin.uploadpack", program)
    # a commit whose tree is not there: reading it asks the "promisor" remote for it
    _commit_object(
        repo,
        f"tree {'1' * 40}\nparent {{parent}}\nauthor {{who}}\ncommitter {{who}}\n\nmissing\n",
    )

    # sanity: plain git runs it
    subprocess.run(  # noqa: ASYNC221
        ["git", "log", "--name-only", "--format=%H"], cwd=repo, capture_output=True, check=False
    )
    if not marker.exists():
        pytest.skip("this git does not fetch that way here; nothing to prove")
    marker.unlink()

    await _read_history(repo)
    assert not marker.exists(), "margin let the repository run a program"


def _tree(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_every_git_command_carries_the_safety_settings() -> None:
    cmd = git_command(["log"])
    for setting in SAFE_GIT_CONFIG:
        assert cmd[cmd.index(setting) - 1] == "-c"
    assert "core.fsmonitor=false" in cmd and "filter.lfs.smudge=" in cmd
    assert "log.showSignature=false" in cmd
    assert cmd[-1] == "log"


def test_reports_carry_no_terminal_escape_sequences() -> None:
    hostile = "\x1b]0;title\x07\x1b[2Jhidden\x9b31m"
    result = AgentResult(
        agent_id="x", agent_version="1", status="ok", summary=hostile,
        findings=[Finding(title=hostile, summary=hostile,
                          evidence=[Evidence(kind="commit", detail=hostile)])],
    )  # fmt: skip
    for report in (to_markdown(result), to_json(result)):
        assert "\x1b" not in report and "\x07" not in report and "\x9b" not in report
    assert "hidden" in to_markdown(result)
    assert json.loads(to_json(result))["summary"] == hostile  # JSON keeps the value, escaped


# ---- 2. reading outside the workspace ------------------------------------------------------


def test_paths_cannot_leave_the_workspace(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (root / "ok.py").write_text("fine", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    ws = Workspace(root=root, source=str(root))
    assert ws.read_text("ok.py") == "fine"
    for escape in ["../secret.txt", "sub/../../secret.txt", str(tmp_path / "secret.txt")]:
        with pytest.raises(InvalidTargetError, match="escapes"):
            ws.read_text(escape)
    assert not ws.exists("../secret.txt")


def test_symlinks_cannot_lead_out_of_the_workspace(tmp_path: Path) -> None:
    root = tmp_path / "ws"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("secret", encoding="utf-8")
    try:
        (root / "link.py").symlink_to(tmp_path / "secret.txt")
    except OSError:
        pytest.skip("symlinks not permitted on this system (covered on Linux CI)")
    with pytest.raises(InvalidTargetError, match="escapes"):
        Workspace(root=root, source=str(root)).read_text("link.py")


# ---- 3. cancelling during a clone ------------------------------------------------------------


@needs_git
async def test_cancelling_during_a_clone_stops_git_and_leaves_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))  # where the clone folder goes
    started = tmp_path / "clone-started"
    # stands in for a long clone: keeps writing into the destination until killed
    slow_clone = (
        "import pathlib, sys, time\n"
        "dest = pathlib.Path(sys.argv[1]); dest.mkdir(parents=True)\n"
        f"pathlib.Path({str(started)!r}).write_text('1')\n"
        "for i in range(600):\n"
        "    (dest / f'f{i}').write_text('x'); time.sleep(0.05)\n"
    )
    loader = GitHubLoader(allow_non_github_urls=True)
    monkeypatch.setattr(
        loader, "_clone_command",
        lambda url, dest, branch: [sys.executable, "-c", slow_clone, str(dest)],
    )  # fmt: skip
    task = asyncio.create_task(loader.load("file:///anything"))
    for _ in range(100):
        if started.exists():
            break
        await asyncio.sleep(0.05)
    assert started.exists(), "the fake clone never started"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.3)  # a process that was not stopped would keep writing
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.startswith("margin-")]  # noqa: ASYNC240
    assert leftovers == [], f"cancelled clone left {leftovers}"


# ---- 4. secrets ------------------------------------------------------------------------------

SENTINEL = "sk-SENTINEL-0123456789abcdef"


async def test_secrets_never_reach_logs_or_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import httpx
    from margin_core.config import get_settings
    from margin_core.llm import create_llm
    from margin_core.llm.catalog import check_connection, list_models

    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LOCAL_LLM_API_KEY", "GITHUB_TOKEN"):
        monkeypatch.setenv(name, SENTINEL)
    monkeypatch.setenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:9")  # nothing listens there
    caplog.set_level(logging.DEBUG)

    texts = [repr(get_settings()), str(get_settings().model_dump())]
    for provider in ("anthropic", "openai", "local"):
        texts.append(repr(create_llm(provider, "m")))
        texts.append((await check_connection(provider, "m")).message)
        try:
            await list_models(provider, timeout_s=2)
        except Exception as exc:  # noqa: BLE001 - we only care what the error says
            texts.append(str(exc))

    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    loader = GitHubLoader(http_client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)))
    texts.append(str(await loader.check_remote_size("owner", "repo")))

    everything = "\n".join(texts + [r.getMessage() for r in caplog.records])
    assert SENTINEL not in everything
    assert os.environ["GITHUB_TOKEN"] == SENTINEL  # it was set; it just never leaked
