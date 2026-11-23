"""Workspace and git commit-patch scanner for leaked secrets."""

from __future__ import annotations

import asyncio
import contextlib
import re
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from margin_core import Evidence, Finding, RunContext
from margin_core.loaders import FileInfo, Workspace
from margin_core.loaders.filters import (
    BINARY_EXTENSIONS,
    IGNORED_DIRS,
    LOCKFILES,
    MINIFIED_SUFFIXES,
    FilterConfig,
    classify_path,
)
from margin_core.loaders.git import (
    READ_ONLY_GIT_CONFIG,
    GitCommandError,
    git_command,
    run_git,
    safe_git_env,
)

from secret_leaks.models import (
    SecretLeaksInput,
    SecretLeaksOutput,
    SecretMatchSummary,
    Severity,
)
from secret_leaks.rules import (
    SEVERITY_RANK,
    CandidateMatch,
    compile_allowlist,
    digest_text,
    scan_line,
    strip_control_chars,
)

_COMMIT_MARKER = "\x1eCOMMIT:"
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_SEVERITY_SCORE: dict[Severity, float] = {
    "high": 1.0,
    "medium": 0.6,
    "low": 0.3,
}
_MAX_FINDINGS = 200
_MAX_GIT_PATCH_BYTES = 16 * 1024 * 1024
_GIT_LOG_TIMEOUT_S = 120.0
_STREAM_CHUNK_BYTES = 65536
_STREAM_POLL_TIMEOUT_S = 0.25
_MAX_STDERR_BYTES = 65536
_MAX_PEM_LINES = 200
_PEM_RULE = "pem_private_key"

# Secrets hide in vendored and generated files too, so those are scanned. Tool and build
# folders (.git, node_modules, .vscode, dist, ...) are still skipped, and the run says so.
SCAN_FILTERS = FilterConfig(include_vendored=True, include_generated=True)


@dataclass
class _RecordedMatch:
    summary: SecretMatchSummary
    digest: str
    raw_repo_path: str


@dataclass
class ScanOutcome:
    output: SecretLeaksOutput
    findings: list[Finding]
    summary: str
    partial: bool = False


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _pem_digest(header: str, body: Sequence[str]) -> str:
    """Digest of a PEM block: its header and body up to and including the END line.

    Keyed on the key material rather than the line number, so a key that moved within a
    file is still recognised in HEAD, and two keys in one file stay distinct.
    """
    block = [header.strip()]
    for line in body[:_MAX_PEM_LINES]:
        block.append(line.strip())
        if "-----END" in line:
            break
    return digest_text("\n".join(block))


def _scan_lines(
    lines: Sequence[str],
    allowlist: list[re.Pattern[str]],
    min_severity: Severity,
) -> list[tuple[int, CandidateMatch, str]]:
    """Scan text lines; returns ``(line_no, candidate, digest)`` for every match."""
    found: list[tuple[int, CandidateMatch, str]] = []
    for idx, line in enumerate(lines):
        for candidate in scan_line(line, allowlist=allowlist, min_severity=min_severity):
            if candidate.rule_id == _PEM_RULE:
                digest = _pem_digest(line, lines[idx + 1 : idx + 1 + _MAX_PEM_LINES])
            else:
                digest = candidate.secret_digest
            found.append((idx + 1, candidate, digest))
    return found


def _read_workspace_file_lines(ws: Workspace, file_info: FileInfo) -> list[str] | None:
    """Read UTF-8 text lines from a workspace file, or return None if binary."""
    raw = ws.abs_path(file_info).read_bytes()
    if b"\x00" in raw:
        return None
    return raw.decode("utf-8", errors="replace").splitlines()


def _is_partial_clone(root: Path) -> bool:
    """Return True when git history blobs may be missing (e.g. a blobless clone)."""
    try:
        out = run_git(
            [
                "config",
                "--get-regexp",
                r"^(remote\..*\.(promisor|partialclonefilter)|extensions\.partialclone)$",
            ],
            cwd=root,
        )
    except (GitCommandError, OSError, subprocess.TimeoutExpired):
        return False
    return bool(out.strip())


def _git_pathspec_exclusions() -> list[str]:
    """Pathspec exclusions so ``git log -p`` skips lockfiles, binaries, and ignored folders."""
    dirs = sorted(IGNORED_DIRS - {".git"})
    return [
        *(f":(glob,exclude)**/{name}" for name in sorted(LOCKFILES)),
        *(f":(glob,exclude)**/*{suffix}" for suffix in MINIFIED_SUFFIXES),
        *(f":(glob,exclude)**/{directory}/**" for directory in dirs),
        *(f":(glob,exclude)**/*{ext}" for ext in sorted(BINARY_EXTENSIONS)),
    ]


class _GitPatchParser:
    """Incremental parser for ``git log -p -U0`` output.

    Tracks unified-diff hunk line counts so lines inside committed patches cannot spoof
    diff headers or commit markers.
    """

    def __init__(self) -> None:
        self.commits_seen: set[str] = set()
        self._current_sha: str | None = None
        self._current_repo_path: str | None = None
        self._old_remaining = 0
        self._new_remaining = 0
        self._new_line_no = 0
        self._in_binary = False

    def feed_line(self, raw_line: str) -> tuple[str, str, int, str] | None:
        raw_line = raw_line.removesuffix("\r")
        if self._old_remaining == 0 and self._new_remaining == 0:
            if raw_line.startswith(_COMMIT_MARKER):
                sha = strip_control_chars(raw_line[len(_COMMIT_MARKER) :].strip())
                self._current_sha = sha or None
                if self._current_sha:
                    self.commits_seen.add(self._current_sha)
                self._current_repo_path = None
                self._in_binary = False
            elif raw_line.startswith("diff --git "):
                self._current_repo_path = None
                self._in_binary = False
            elif raw_line.startswith("Binary files "):
                self._in_binary = True
                self._current_repo_path = None
            elif raw_line.startswith("+++ "):
                target = raw_line[4:].rstrip("\t")
                if target == "/dev/null":
                    self._current_repo_path = None
                elif target.startswith("b/"):
                    self._current_repo_path = target[2:]
                else:
                    self._current_repo_path = target
            elif raw_line.startswith("@@ "):
                hunk = _HUNK_RE.match(raw_line)
                if hunk is not None:
                    self._old_remaining = int(hunk.group(2)) if hunk.group(2) is not None else 1
                    self._new_line_no = int(hunk.group(3))
                    self._new_remaining = int(hunk.group(4)) if hunk.group(4) is not None else 1
            return None

        if raw_line.startswith("\\"):
            return None
        if raw_line.startswith("-"):
            if self._old_remaining > 0:
                self._old_remaining -= 1
            return None
        if raw_line.startswith("+"):
            if self._new_remaining > 0:
                self._new_remaining -= 1
            result: tuple[str, str, int, str] | None = None
            if not self._in_binary and self._current_sha and self._current_repo_path:
                result = (
                    self._current_sha,
                    self._current_repo_path,
                    self._new_line_no,
                    raw_line[1:],
                )
            self._new_line_no += 1
            return result
        if raw_line.startswith(" "):
            if self._old_remaining > 0:
                self._old_remaining -= 1
            if self._new_remaining > 0:
                self._new_remaining -= 1
            self._new_line_no += 1
            return None

        self._old_remaining = 0
        self._new_remaining = 0
        if raw_line.startswith(_COMMIT_MARKER) or raw_line.startswith("diff --git "):
            return self.feed_line(raw_line)
        return None


def _parse_git_log_patches(
    patch_output: str,
) -> tuple[int, list[tuple[str, str, int, str]]]:
    """Parse ``git log -p -U0`` output into ``(commits_scanned, added_lines)``."""
    parser = _GitPatchParser()
    added_lines: list[tuple[str, str, int, str]] = []
    # Split strictly on LF so git's \x1e marker and embedded Unicode separators never split lines.
    for raw_line in patch_output.split("\n"):
        added = parser.feed_line(raw_line)
        if added is not None:
            added_lines.append(added)
    return len(parser.commits_seen), added_lines


async def _stop_process(proc: asyncio.subprocess.Process) -> None:
    """Kill a subprocess if still running and wait for it to exit."""
    if proc.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await asyncio.shield(proc.wait())


async def _read_capped_stream(stream: asyncio.StreamReader | None, max_bytes: int) -> bytes:
    """Drain an async stream while keeping at most ``max_bytes`` in memory."""
    if stream is None:
        return b""
    buf = bytearray()
    while True:
        chunk = await stream.read(_STREAM_CHUNK_BYTES)
        if not chunk:
            break
        remaining = max_bytes - len(buf)
        if remaining > 0:
            buf.extend(chunk[:remaining])
    return bytes(buf)


def _load_head_files(
    ws: Workspace,
    repo_paths: set[str],
    head_cache: dict[str, str | None],
) -> None:
    """Populate ``head_cache`` with raw file contents at ``HEAD`` for ``repo_paths``."""
    if ws.git is None or ws.git.head is None:
        return
    for repo_path in sorted(repo_paths):
        if repo_path in head_cache:
            continue
        try:
            head_cache[repo_path] = run_git(
                ["show", f"HEAD:{repo_path}"],
                cwd=ws.git.root,
                timeout_s=30.0,
            )
        except (GitCommandError, OSError, subprocess.TimeoutExpired):
            head_cache[repo_path] = None


def _extract_digests(
    text: str | None,
    allowlist: list[re.Pattern[str]],
    min_severity: Severity,
) -> set[str]:
    if not text:
        return set()
    return {digest for _, _, digest in _scan_lines(text.splitlines(), allowlist, min_severity)}


def _repo_path_for(ws: Workspace, ws_rel_path: str) -> str:
    if ws.git is None or not ws.git.prefix:
        return ws_rel_path
    return f"{ws.git.prefix}/{ws_rel_path}"


async def _resolve_in_head(
    ws: Workspace,
    ctx: RunContext,
    allowlist: list[re.Pattern[str]],
    min_severity: Severity,
    workspace_records: dict[tuple[str, str, str], _RecordedMatch],
    history_records: dict[tuple[str, str, str], _RecordedMatch],
) -> None:
    """Set accurate ``in_head`` status for workspace and git-history matches."""
    if ws.git is None:
        return
    if ws.git.head is None:
        for record in workspace_records.values():
            record.summary = record.summary.model_copy(update={"in_head": False})
        return

    ctx.check_cancelled()
    repo_paths_to_check: set[str] = {
        *(record.raw_repo_path for record in workspace_records.values()),
        *(record.raw_repo_path for record in history_records.values()),
    }
    if not repo_paths_to_check:
        return

    head_cache: dict[str, str | None] = {}
    await asyncio.to_thread(_load_head_files, ws, repo_paths_to_check, head_cache)
    head_digests = {
        repo_path: _extract_digests(text, allowlist, min_severity)
        for repo_path, text in head_cache.items()
    }

    for record in workspace_records.values():
        in_head = record.digest in head_digests.get(record.raw_repo_path, set())
        record.summary = record.summary.model_copy(update={"in_head": in_head})

    for record in history_records.values():
        in_head = record.digest in head_digests.get(record.raw_repo_path, set())
        record.summary = record.summary.model_copy(update={"in_head": in_head})


def _read_and_scan(
    ws: Workspace,
    file_info: FileInfo,
    allowlist: list[re.Pattern[str]],
    min_severity: Severity,
) -> list[tuple[int, CandidateMatch, str]] | None:
    lines = _read_workspace_file_lines(ws, file_info)
    return None if lines is None else _scan_lines(lines, allowlist, min_severity)


async def _scan_workspace_files(
    ws: Workspace,
    params: SecretLeaksInput,
    ctx: RunContext,
    allowlist: list[re.Pattern[str]],
) -> tuple[dict[tuple[str, str, str], _RecordedMatch], int, bool]:
    records: dict[tuple[str, str, str], _RecordedMatch] = {}
    partial = False
    files_scanned = 0
    total_files = len(ws.files)

    ctx.report_progress("workspace", f"Scanning {_count(total_files, 'file')}", 0.1)
    for idx, file_info in enumerate(ws.files):
        if idx % 25 == 0:
            ctx.check_cancelled()
            frac = 0.1 + 0.4 * (idx / max(total_files, 1))
            ctx.report_progress("workspace", strip_control_chars(file_info.path), frac)

        try:
            # Reading and the regexes run off the event loop, so the API stays responsive.
            found = await asyncio.to_thread(
                _read_and_scan, ws, file_info, allowlist, params.min_severity
            )
        except OSError as exc:
            ctx.warn(f"Could not read {strip_control_chars(file_info.path)}: {exc}")
            partial = True
            continue

        if found is None:
            continue

        files_scanned += 1
        safe_path = strip_control_chars(file_info.path)
        raw_repo_path = _repo_path_for(ws, file_info.path)
        for line_no, candidate, digest in found:
            key = (candidate.rule_id, safe_path, digest)
            if key in records:
                continue
            records[key] = _RecordedMatch(
                summary=SecretMatchSummary(
                    rule_id=candidate.rule_id,
                    rule_name=candidate.rule_name,
                    severity=candidate.severity,
                    source="workspace",
                    file_path=safe_path,
                    line=line_no,
                    commit_sha=None,
                    in_head=None if ws.git is None else True,
                    redacted_preview=strip_control_chars(candidate.redacted_preview),
                    entropy=candidate.entropy,
                ),
                digest=digest,
                raw_repo_path=raw_repo_path,
            )

    return records, files_scanned, partial


def _warn_skipped(ws: Workspace, ctx: RunContext) -> None:
    """Say which files were not scanned, since a secret may sit in any of them."""
    too_large = [s.path for s in ws.skipped if s.reason == "too_large"]
    folders = [s.path for s in ws.skipped if s.reason == "ignored_dir"]
    parts = []
    if too_large:
        parts.append(f"{_count(len(too_large), 'file')} over the size limit")
    if folders:
        names = sorted({PurePosixPath(p.rstrip("/")).name for p in folders})
        shown = ", ".join(names[:4]) + (", ..." if len(names) > 4 else "")
        parts.append(f"{_count(len(folders), 'tool or build folder')} ({shown})")
    if parts:
        ctx.warn(f"Not scanned: {' and '.join(parts)}.")


def _record_history_match(
    sha: str,
    repo_path: str,
    ws_path: str,
    line_no: int,
    candidate: CandidateMatch,
    digest: str,
    workspace_records: dict[tuple[str, str, str], _RecordedMatch],
    history_records: dict[tuple[str, str, str], _RecordedMatch],
) -> None:
    safe_path = strip_control_chars(ws_path)
    key = (candidate.rule_id, safe_path, digest)
    if key in workspace_records:
        existing = workspace_records[key]
        existing.summary = existing.summary.model_copy(update={"commit_sha": sha})
        return

    # git log walks newest -> oldest, so overwriting keeps the commit that introduced it.
    history_records[key] = _RecordedMatch(
        summary=SecretMatchSummary(
            rule_id=candidate.rule_id,
            rule_name=candidate.rule_name,
            severity=candidate.severity,
            source="git_history",
            file_path=safe_path,
            line=line_no,
            commit_sha=sha,
            in_head=False,
            redacted_preview=strip_control_chars(candidate.redacted_preview),
            entropy=candidate.entropy,
        ),
        digest=digest,
        raw_repo_path=repo_path,
    )


@dataclass
class _OpenPem:
    """A PEM header added in a commit, collecting the added lines of its body."""

    sha: str
    repo_path: str
    ws_path: str
    line_no: int
    candidate: CandidateMatch
    header: str
    body: list[str]

    @property
    def next_line(self) -> int:
        return self.line_no + 1 + len(self.body)


async def _scan_git_history(
    ws: Workspace,
    params: SecretLeaksInput,
    ctx: RunContext,
    allowlist: list[re.Pattern[str]],
    workspace_records: dict[tuple[str, str, str], _RecordedMatch],
) -> tuple[dict[tuple[str, str, str], _RecordedMatch], int, bool]:
    history_records: dict[tuple[str, str, str], _RecordedMatch] = {}

    if ws.git is None or ws.git.head is None or not params.scan_git_history:
        return history_records, 0, False
    git = ws.git

    ctx.check_cancelled()
    if await asyncio.to_thread(_is_partial_clone, git.root):
        ctx.warn(
            "Skipped git history scan: this repository is a partial clone without local "
            "historical file contents."
        )
        return history_records, 0, True

    ctx.report_progress(
        "git_history",
        f"Scanning up to {params.history_depth} git commit(s)",
        0.55,
    )
    read_only = [arg for setting in READ_ONLY_GIT_CONFIG for arg in ("-c", setting)]
    positive_pathspecs = git.pathspecs if git.pathspecs else ["."]
    git_args = [
        "-c",
        "core.quotepath=off",
        "log",
        f"--max-count={params.history_depth}",
        f"--format={_COMMIT_MARKER}%H",
        "-p",
        "-U0",
        "--diff-filter=AM",
        "--no-merges",
        "--no-renames",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--",
        *positive_pathspecs,
        *_git_pathspec_exclusions(),
    ]
    cmd = git_command([*read_only, *git_args])
    env = {**safe_git_env(), "GIT_NO_LAZY_FETCH": "1"}

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=git.root,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except OSError as exc:
        ctx.warn(f"Git history scan could not start git: {strip_control_chars(str(exc))}")
        return history_records, 0, True

    assert proc.stdout is not None
    stderr_task = asyncio.create_task(_read_capped_stream(proc.stderr, _MAX_STDERR_BYTES))
    read_task: asyncio.Task[bytes] | None = None

    parser = _GitPatchParser()
    pending = bytearray()
    bytes_read = 0
    lines_processed = 0
    truncated = False
    timed_out = False
    deadline = time.monotonic() + _GIT_LOG_TIMEOUT_S

    open_pem: _OpenPem | None = None

    def _close_pem() -> None:
        nonlocal open_pem
        if open_pem is not None:
            pem = open_pem
            open_pem = None
            _record_history_match(
                pem.sha,
                pem.repo_path,
                pem.ws_path,
                pem.line_no,
                pem.candidate,
                _pem_digest(pem.header, pem.body),
                workspace_records,
                history_records,
            )

    def _consume_line(line_bytes: bytes) -> None:
        nonlocal lines_processed, open_pem
        added = parser.feed_line(line_bytes.decode("utf-8", errors="replace"))
        if added is None:
            return
        sha, repo_path, line_no, line_text = added
        lines_processed += 1
        if lines_processed % 500 == 0:
            ctx.check_cancelled()
            frac = 0.6 + 0.3 * min(len(parser.commits_seen) / max(params.history_depth, 1), 1.0)
            ctx.report_progress("git_history", f"Checking commit {sha[:12]}", frac)

        if open_pem is not None:
            continues = (
                (sha, repo_path) == (open_pem.sha, open_pem.repo_path)
                and line_no == open_pem.next_line
                and len(open_pem.body) < _MAX_PEM_LINES
            )
            if continues:
                open_pem.body.append(line_text)
                if "-----END" in line_text:
                    _close_pem()
                return
            _close_pem()

        ws_path = git.to_workspace_path(repo_path)
        if ws_path is None or not classify_path(ws_path, SCAN_FILTERS).keep:
            return
        for candidate in scan_line(
            line_text, allowlist=allowlist, min_severity=params.min_severity
        ):
            if candidate.rule_id == _PEM_RULE:
                _close_pem()
                open_pem = _OpenPem(sha, repo_path, ws_path, line_no, candidate, line_text, [])
                continue
            _record_history_match(
                sha,
                repo_path,
                ws_path,
                line_no,
                candidate,
                candidate.secret_digest,
                workspace_records,
                history_records,
            )

    try:
        while True:
            ctx.check_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                break

            if read_task is None:
                read_task = asyncio.create_task(proc.stdout.read(_STREAM_CHUNK_BYTES))

            done, _ = await asyncio.wait(
                {read_task},
                timeout=min(_STREAM_POLL_TIMEOUT_S, remaining),
            )
            if not done:
                continue

            chunk = read_task.result()
            read_task = None
            if not chunk:
                if pending:
                    _consume_line(bytes(pending))
                    pending.clear()
                break

            if bytes_read + len(chunk) > _MAX_GIT_PATCH_BYTES:
                allowed = max(_MAX_GIT_PATCH_BYTES - bytes_read, 0)
                chunk = chunk[:allowed]
                truncated = True

            bytes_read += len(chunk)
            if chunk:
                pending.extend(chunk)
                start = 0
                while True:
                    nl = pending.find(b"\n", start)
                    if nl == -1:
                        if start:
                            del pending[:start]
                        break
                    _consume_line(bytes(pending[start:nl]))
                    start = nl + 1

            if truncated:
                break
    except BaseException:
        if read_task is not None and not read_task.done():
            read_task.cancel()
            with contextlib.suppress(BaseException):
                await read_task
        await _stop_process(proc)
        stderr_task.cancel()
        with contextlib.suppress(BaseException):
            await stderr_task
        raise

    if read_task is not None and not read_task.done():
        read_task.cancel()
        with contextlib.suppress(BaseException):
            await read_task
    _close_pem()

    partial = False
    if truncated or timed_out:
        await _stop_process(proc)
        stderr_task.cancel()
        with contextlib.suppress(BaseException):
            await stderr_task
        if timed_out:
            ctx.warn(
                f"Git history scan timed out after {_GIT_LOG_TIMEOUT_S:.0f}s; "
                "older commits were skipped."
            )
        else:
            limit_mib = _MAX_GIT_PATCH_BYTES / (1024 * 1024)
            limit_label = (
                f"{limit_mib:.0f} MiB" if limit_mib >= 1 else f"{_MAX_GIT_PATCH_BYTES} bytes"
            )
            ctx.warn(
                f"Git history scan stopped after reaching the {limit_label} patch limit; "
                "older commits were skipped."
            )
        partial = True
    else:
        await proc.wait()
        stderr_bytes = await stderr_task
        if proc.returncode != 0:
            err_text = strip_control_chars(stderr_bytes.decode("utf-8", errors="replace").strip())
            ctx.warn(f"Git history scan could not inspect commit patches: {err_text}")
            partial = True

    return history_records, len(parser.commits_seen), partial


def _build_finding(match: SecretMatchSummary) -> Finding:
    safe_path = strip_control_chars(match.file_path)
    safe_preview = strip_control_chars(match.redacted_preview)
    safe_sha = strip_control_chars(match.commit_sha) if match.commit_sha else None
    loc = f"{safe_path}:{match.line}" if match.line is not None else safe_path
    if match.source == "workspace":
        head_note = ""
        if match.in_head is True:
            head_note = " (present in HEAD)"
        elif match.in_head is False:
            head_note = " (uncommitted working tree change)"
        summary = f"Detected {match.rule_name} ({safe_preview}) in workspace file {loc}{head_note}."
        evidence = [
            Evidence(
                kind="file",
                location=loc,
                detail=f"Rule {match.rule_id} matched redacted preview {safe_preview}.",
            )
        ]
        if safe_sha:
            detail = f"Introduced in commit {safe_sha[:12]}; in_head={match.in_head}."
            evidence.append(
                Evidence(
                    kind="commit",
                    location=safe_sha,
                    detail=detail,
                )
            )
    else:
        short_sha = safe_sha[:12] if safe_sha else "unknown"
        status_note = "still present in HEAD" if match.in_head else "deleted from HEAD"
        summary = (
            f"Detected {match.rule_name} ({safe_preview}) in git commit {short_sha} "
            f"at {loc} ({status_note})."
        )
        evidence = [
            Evidence(
                kind="commit",
                location=safe_sha,
                detail=f"Commit {short_sha} added secret in {loc}; in_head={match.in_head}.",
            ),
            Evidence(
                kind="file",
                location=loc,
                detail=f"Rule {match.rule_id} matched redacted preview {safe_preview}.",
            ),
        ]

    return Finding(
        title=f"{match.rule_name} in {safe_path}",
        severity_or_score=_SEVERITY_SCORE[match.severity],
        summary=summary,
        evidence=evidence,
    )


async def scan_workspace(
    ws: Workspace,
    params: SecretLeaksInput,
    ctx: RunContext,
) -> ScanOutcome:
    """Scan workspace files and optionally git history for secrets."""
    allowlist = compile_allowlist(params.allowlist_patterns)

    workspace_records, files_scanned, ws_partial = await _scan_workspace_files(
        ws, params, ctx, allowlist
    )
    _warn_skipped(ws, ctx)
    history_records, commits_scanned, git_partial = await _scan_git_history(
        ws, params, ctx, allowlist, workspace_records
    )
    await _resolve_in_head(
        ws, ctx, allowlist, params.min_severity, workspace_records, history_records
    )

    partial = ws_partial or git_partial

    all_matches = [
        *[r.summary for r in workspace_records.values()],
        *[r.summary for r in history_records.values()],
    ]
    all_matches.sort(key=lambda m: (-SEVERITY_RANK[m.severity], m.source, m.file_path, m.line or 0))

    counts_by_severity: dict[Severity, int] = {"high": 0, "medium": 0, "low": 0}
    for m in all_matches:
        counts_by_severity[m.severity] += 1

    rules_triggered = sorted({m.rule_id for m in all_matches})
    workspace_count = sum(1 for m in all_matches if m.source == "workspace")
    history_count = sum(1 for m in all_matches if m.source == "git_history")

    shown_matches = all_matches[:_MAX_FINDINGS]
    output = SecretLeaksOutput(
        target=strip_control_chars(ws.source),
        total_matches=len(all_matches),
        counts_by_severity=counts_by_severity,
        workspace_matches=workspace_count,
        git_history_matches=history_count,
        files_scanned=files_scanned,
        commits_scanned=commits_scanned,
        rules_triggered=rules_triggered,
        matches=shown_matches,
    )

    findings = [_build_finding(m) for m in shown_matches]
    if len(all_matches) > _MAX_FINDINGS:
        ctx.warn(f"Showing the first {_MAX_FINDINGS} of {len(all_matches)} matches.")

    files = _count(files_scanned, "file")
    commits = _count(commits_scanned, "commit")
    if output.total_matches == 0:
        if params.scan_git_history and ws.git is not None and not git_partial:
            summary = f"No secrets found in {files} or {commits}."
        elif params.scan_git_history and ws.git is not None:
            summary = f"No secrets found in {files}. The git history scan was skipped or cut short."
        else:
            summary = f"No secrets found in {files}."
    else:
        found = (
            "1 possible secret"
            if output.total_matches == 1
            else (f"{output.total_matches} possible secrets")
        )
        summary = (
            f"Found {found} ({counts_by_severity['high']} high, "
            f"{counts_by_severity['medium']} medium, {counts_by_severity['low']} low): "
            f"{workspace_count} in the files, {history_count} only in git history. "
            f"Scanned {files} and {commits}."
        )

    return ScanOutcome(
        output=output,
        findings=findings,
        summary=summary,
        partial=partial,
    )
