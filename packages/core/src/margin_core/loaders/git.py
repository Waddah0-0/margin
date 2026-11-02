"""Thin wrappers around the ``git`` CLI. Repository code is never executed: see
:data:`SAFE_GIT_CONFIG`."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from margin_core.loaders.base import GitCommit, GitInfo
from margin_core.logging import get_logger

logger = get_logger("git")

RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"
_LOG_FORMAT = RECORD_SEP + FIELD_SEP.join(
    ["%H", "%an", "%ae", "%aI", "%cn", "%ce", "%cI", "%P", "%B"]
)


class GitCommandError(RuntimeError):
    """A git command exited with a non-zero status."""


def git_available() -> bool:
    return shutil.which("git") is not None


# Passed on every git command line, where they override any config, including a repository's
# own .git/config. A folder we are pointed at is untrusted: its config could name programs for
# git to run (core.fsmonitor), hooks could run on checkout, and Git LFS could download files
# from another server past our size limits. log.showSignature would make ``git log`` run the
# program named by gpg.program on any signed commit.
SAFE_GIT_CONFIG = (
    "core.fsmonitor=false",
    "core.hooksPath=" + os.devnull,
    "filter.lfs.smudge=",
    "filter.lfs.process=",
    "filter.lfs.required=false",
    "log.showSignature=false",
    "i18n.logOutputEncoding=UTF-8",
)

# Added when reading history, which never needs the network. A repository that declares a
# "promisor" remote and leaves out an object makes git fetch it, and a fetch runs programs the
# repository names (core.sshCommand, remote.<name>.uploadpack). A clone does fetch, so it goes
# without these.
READ_ONLY_GIT_CONFIG = ("protocol.allow=never",)


def safe_git_env() -> dict[str, str]:
    """Environment that prevents git from ever prompting (terminal, GUI, credential manager)
    and from fetching Git LFS content."""
    env = dict(os.environ)
    env.update(
        {
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ASKPASS": "",
            "SSH_ASKPASS": "",
            "GCM_INTERACTIVE": "never",
            "GIT_LFS_SKIP_SMUDGE": "1",
        }
    )
    return env


def git_command(args: list[str]) -> list[str]:
    """``git <args>`` with the safety settings in front."""
    cmd = ["git"]
    for setting in SAFE_GIT_CONFIG:
        cmd += ["-c", setting]
    return cmd + args


def run_git(args: list[str], cwd: Path | None = None, timeout_s: float = 60.0) -> str:
    """Run a command that only reads the repository, with no network, and return stdout (UTF-8).
    Raises :class:`GitCommandError`."""
    read_only = [arg for setting in READ_ONLY_GIT_CONFIG for arg in ("-c", setting)]
    cmd = git_command([*read_only, *args])
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        timeout=timeout_s,
        env={**safe_git_env(), "GIT_NO_LAZY_FETCH": "1"},  # git 2.45+; older ones have the config
        stdin=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        raise GitCommandError(f"git {' '.join(args)} failed: {stderr}")
    return proc.stdout.decode("utf-8", errors="replace")


def detect_git(path: Path, scopes: list[str] | None = None) -> GitInfo | None:
    """Return :class:`GitInfo` if ``path`` is inside a git work tree, else ``None``.

    History is limited to ``path`` (when it is a sub-folder of the repository) and, within
    it, to ``scopes`` (workspace-relative paths), so commit signals only describe the code
    being analysed.
    """
    if not git_available():
        return None
    try:
        top = run_git(["rev-parse", "--show-toplevel"], cwd=path).strip()
    except (GitCommandError, OSError, subprocess.TimeoutExpired):
        return None
    root = Path(top)
    try:
        prefix = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        logger.warning("Could not place %s inside repository %s; using full history", path, root)
        prefix = "."
    prefix = "" if prefix == "." else prefix
    pathspecs = [f"{prefix}/{s}" if prefix else s for s in scopes or [] if s]
    if not pathspecs and prefix:
        pathspecs = [prefix]
    head: str | None
    try:
        head = run_git(["rev-parse", "HEAD"], cwd=root).strip()
    except GitCommandError:
        head = None  # repository without commits
    try:
        branch = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root).strip() or None
    except GitCommandError:
        branch = None
    return GitInfo(root=root, head=head, branch=branch, prefix=prefix, pathspecs=pathspecs)


def parse_log(output: str) -> list[GitCommit]:
    """Parse output produced with :data:`_LOG_FORMAT`."""
    commits: list[GitCommit] = []
    for record in output.split(RECORD_SEP):
        if not record.strip():
            continue
        fields = record.split(FIELD_SEP, 8)
        if len(fields) != 9:
            logger.warning("Skipping malformed git log record")
            continue
        sha, an, ae, ad, cn, ce, cd, parents, message = fields
        commits.append(
            GitCommit(
                sha=sha.strip(),
                author_name=an,
                author_email=ae,
                authored_at=datetime.fromisoformat(ad),
                committer_name=cn,
                committer_email=ce,
                committed_at=datetime.fromisoformat(cd),
                parents=parents.split(),
                message=message.strip("\n"),
            )
        )
    return commits


def _pathspec_args(pathspecs: list[str] | None) -> list[str]:
    return ["--", *pathspecs] if pathspecs else []


def read_commits_sync(
    root: Path, max_count: int | None = None, pathspecs: list[str] | None = None
) -> list[GitCommit]:
    args = ["log", f"--format={_LOG_FORMAT}"]
    if max_count is not None:
        args.append(f"--max-count={max_count}")
    return parse_log(run_git(args + _pathspec_args(pathspecs), cwd=root, timeout_s=120.0))


async def read_commits(
    root: Path, max_count: int | None = None, pathspecs: list[str] | None = None
) -> list[GitCommit]:
    return await asyncio.to_thread(read_commits_sync, root, max_count, pathspecs)


def read_changed_files_sync(
    root: Path, pathspecs: list[str] | None = None, max_count: int | None = None
) -> list[tuple[str, list[str]]]:
    """``(sha, repo-relative paths)`` per commit, newest first, without reading any blob.

    Only ``--name-only --no-renames`` is safe on blobless clones: ``--numstat``, ``--stat``,
    ``-p`` and rename detection need file contents and would download every historical blob
    (verified 2026-10-18: ``--numstat`` fetched all 97 missing blobs of a test clone).
    """
    args = [
        "-c",
        "core.quotepath=off",
        "log",
        "--name-only",
        "--no-renames",
        f"--format={RECORD_SEP}%H",
    ]
    if max_count is not None:
        args.append(f"--max-count={max_count}")
    output = run_git(args + _pathspec_args(pathspecs), cwd=root, timeout_s=120.0)
    changes: list[tuple[str, list[str]]] = []
    for record in output.split(RECORD_SEP):
        lines = [line for line in record.splitlines() if line.strip()]
        if lines:
            changes.append((lines[0].strip(), lines[1:]))
    return changes


async def read_changed_files(
    root: Path, pathspecs: list[str] | None = None, max_count: int | None = None
) -> list[tuple[str, list[str]]]:
    return await asyncio.to_thread(read_changed_files_sync, root, pathspecs, max_count)
