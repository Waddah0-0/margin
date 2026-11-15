"""Reads the history with one ``git log``. Only names and statuses are asked for, never file
contents, so it also works in the blobless clones margin makes of GitHub repositories."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from margin_core.loaders.git import GitCommandError, run_git

RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"
_FORMAT = RECORD_SEP + FIELD_SEP.join(["%H", "%P", "%an", "%aI", "%D", "%s", "%b"]) + FIELD_SEP
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")


@dataclass
class Change:
    status: str  # A added, M changed, D deleted, R renamed
    path: str
    old: str | None = None


@dataclass
class RawCommit:
    hash: str
    parents: list[str]
    author: str
    date: datetime
    subject: str
    body: str = ""
    tags: list[str] = field(default_factory=list)
    branches: list[str] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)

    @property
    def is_merge(self) -> bool:
        return len(self.parents) > 1


def clean(text: str, limit: int) -> str:
    """One line of text from a repository: no control characters, and not too long."""
    text = " ".join(_CONTROL.sub(" ", text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def is_partial_clone(root: Path) -> bool:
    """True when file contents may be missing (a blobless clone), so only exact renames can
    be followed."""
    try:
        out = run_git(
            ["config", "--get-regexp", r"^remote\..*\.(promisor|partialclonefilter)$"], cwd=root
        )
    except GitCommandError:
        return False
    return bool(out.strip())


def count_commits(root: Path, rev: str, pathspecs: list[str]) -> int:
    out = run_git(["rev-list", "--count", rev, "--", *pathspecs], cwd=root)
    return int(out.strip() or 0)


def read_history(
    root: Path, rev: str, pathspecs: list[str], max_commits: int, similar_renames: bool
) -> list[RawCommit]:
    """The newest ``max_commits`` commits reachable from ``rev``, newest first, with children
    always before their parents."""
    args = [
        "-c",
        "core.quotepath=false",
        "log",
        "--topo-order",
        f"-n{max_commits}",
        "--no-color",
        "--no-ext-diff",
        "--name-status",
        # 100% only compares object ids; anything lower would need the file contents
        "-M" if similar_renames else "-M100%",
        f"--format={_FORMAT}",
    ]
    if pathspecs:
        args.append("--parents")  # parents rewritten to the commits that are shown
    out = run_git([*args, rev, "--", *pathspecs], cwd=root, timeout_s=180.0)
    return parse_history(out)


def parse_history(output: str) -> list[RawCommit]:
    commits: list[RawCommit] = []
    for record in output.split(RECORD_SEP)[1:]:
        fields = record.split(FIELD_SEP, 6)
        if len(fields) < 7:
            continue
        sha, parents, author, date, refs, subject, rest = fields
        body, _, changes = rest.rpartition(FIELD_SEP)
        try:
            when = datetime.fromisoformat(date)
        except ValueError:
            continue
        tags, branches = _refs(refs)
        commits.append(
            RawCommit(
                hash=sha,
                parents=parents.split(),
                author=clean(author, 80) or "unknown",
                date=when,
                subject=clean(subject, 200) or "(no message)",
                body=body,
                tags=tags,
                branches=branches,
                changes=_changes(changes),
            )
        )
    return commits


def _refs(text: str) -> tuple[list[str], list[str]]:
    tags: list[str] = []
    branches: list[str] = []
    for ref in (part.strip() for part in text.split(",")):
        if ref.startswith("tag: "):
            tags.append(clean(ref[5:], 60))
        elif ref.startswith("HEAD -> "):
            branches.append(clean(ref[8:], 60))
        elif ref and ref != "HEAD" and not ref.endswith("/HEAD"):
            branches.append(clean(ref, 60))
    return tags, branches


def _changes(text: str) -> list[Change]:
    changes: list[Change] = []
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) < 2 or not parts[0]:
            continue
        status = parts[0][0]
        if status in "RC" and len(parts) >= 3:
            # a copy leaves the old file where it was, so the new one is simply added
            changes.append(
                Change("R", parts[2], parts[1]) if status == "R" else Change("A", parts[2])
            )
        elif status in "AD":
            changes.append(Change(status, parts[1]))
        else:
            changes.append(Change("M", parts[1]))
    return changes
