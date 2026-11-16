"""What a plain graph doesn't show: notes for single commits, and findings across many.

Everything here is counted from the history. Nothing is about a person: authors are only used
to tell whether one area has a single author, and that author is not named.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import PurePosixPath
from statistics import median

from commit_graph.chapters import area
from commit_graph.files import Life
from commit_graph.history import RawCommit
from commit_graph.models import Coupling, FixChain, Hotspot, Note, OnePersonArea

BIG_COMMIT_FILES = 40
QUIET_DAYS = 14
FIX_MINUTES = 60
MIN_HOTSPOT_TOUCHES = 5
MIN_TOGETHER = 5
MIN_SHARE = 0.6
MAX_FILES_FOR_PAIRS = 25
MIN_AREA_TOUCHES = 20
ONE_PERSON_SHARE = 0.9
TOP = 5

_FIX = re.compile(r"^(fix|fixed|fixes|fixing|hotfix|oops|typo)\b", re.I)
_REVERT = re.compile(r"^(revert\b|reverted\b|this reverts)", re.I)
_NOT_CODE = {
    ".md", ".rst", ".txt", ".lock", ".toml", ".json", ".yaml", ".yml", ".cfg", ".ini", ".svg",
}  # fmt: skip
_TEST = re.compile(r"(^|[/_.-])tests?([/_.-]|$)|\.spec\.|conftest", re.I)


@dataclass
class Insights:
    notes: list[list[Note]]
    hotspots: list[Hotspot] = field(default_factory=list)
    couplings: list[Coupling] = field(default_factory=list)
    fix_chains: list[FixChain] = field(default_factory=list)
    one_person_areas: list[OnePersonArea] = field(default_factory=list)


def plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def _ancestors(commits: Sequence[RawCommit], rows: dict[str, int]) -> list[int]:
    """For each row, the set of rows it can reach (itself included), as bits of an integer."""
    reach = [0] * len(commits)
    for row in range(len(commits) - 1, -1, -1):
        bits = 1 << row
        for parent in commits[row].parents:
            if parent in rows:
                bits |= reach[rows[parent]]
        reach[row] = bits
    return reach


def _quiet_days(commits: Sequence[RawCommit]) -> list[int]:
    """Whole days since the commit before, by date, in the whole history shown.

    A branch that starts from an old commit is not a quiet spell: the gap is measured from
    the last commit anyone made, not from the commit's own parent.
    """
    quiet = [0] * len(commits)
    by_date = sorted(range(len(commits)), key=lambda row: commits[row].date)
    for earlier, row in zip(by_date, by_date[1:], strict=False):
        quiet[row] = (commits[row].date - commits[earlier].date).days
    return quiet


def _commit_notes(commits: Sequence[RawCommit], rows: dict[str, int]) -> list[list[Note]]:
    notes: list[list[Note]] = [[] for _ in commits]
    reach = _ancestors(commits, rows)
    sizes = [len(c.changes) for c in commits if c.changes]
    big = max(BIG_COMMIT_FILES, 10 * int(median(sizes))) if sizes else BIG_COMMIT_FILES
    quiet_before = _quiet_days(commits)
    for row, commit in enumerate(commits):
        if not commit.parents:
            notes[row].append(Note(kind="root", text="The first commit"))
        first = rows.get(commit.parents[0]) if commit.parents else None
        quiet = quiet_before[row]
        if quiet >= QUIET_DAYS:
            notes[row].append(Note(kind="gap", text=f"After {quiet} quiet days"))
        if commit.is_merge and first is not None and commit.parents[1] in rows:
            side = reach[rows[commit.parents[1]]] & ~reach[first]
            if side:
                oldest = commits[side.bit_length() - 1]
                days = (commit.date - oldest.date).days
                text = f"Merged a branch of {plural(side.bit_count(), 'commit')}"
                if days >= 1:
                    text += f", {plural(days, 'day')} after it started"
                notes[row].append(Note(kind="merge", text=text))
        if len(commit.changes) >= big:
            notes[row].append(Note(kind="big", text=f"Touched {len(commit.changes)} files"))
        if _REVERT.match(commit.subject):
            notes[row].append(Note(kind="revert", text="Undid an earlier commit", flagged=True))
    return notes


def _fix_chains(
    commits: Sequence[RawCommit], rows: dict[str, int], touched: Sequence[Sequence[int]]
) -> list[list[int]]:
    """Runs of quick fixes, as rows: the first commit, then each fix made within the hour by
    the same author to a file the commit before it also changed."""
    chain_ending_at: dict[int, list[int]] = {}
    extended: set[int] = set()
    for row in range(len(commits) - 1, -1, -1):
        commit = commits[row]
        if commit.is_merge or len(commit.parents) != 1 or not _FIX.match(commit.subject):
            continue
        before = rows.get(commit.parents[0])
        if before is None or commits[before].is_merge:
            continue
        minutes = (commit.date - commits[before].date).total_seconds() / 60
        if not 0 <= minutes <= FIX_MINUTES or commit.author != commits[before].author:
            continue
        if not set(touched[row]) & set(touched[before]):
            continue
        chain_ending_at[row] = [*chain_ending_at.get(before, [before]), row]
        extended.add(before)
    return [
        chain for end, chain in chain_ending_at.items() if end not in extended and len(chain) >= 3
    ]


def _hotspots(
    commits: Sequence[RawCommit],
    lives: Sequence[Life],
    lines_of: Callable[[str], int | None],
) -> list[Hotspot]:
    """Code files that change often and are large: the usual home of bugs."""
    busy = sorted(
        (
            life
            for life in lives
            if life.alive
            and life.touches >= MIN_HOTSPOT_TOUCHES
            and PurePosixPath(life.path).suffix.lower() not in _NOT_CODE
        ),
        key=lambda life: -life.touches,
    )[:30]
    scored: list[tuple[float, Life, int]] = []
    for life in busy:
        lines = lines_of(life.path)
        if lines is not None:  # None: not a file margin analyses (generated, vendored, binary)
            scored.append((life.touches * math.log2(lines + 2), life, lines))
    scored.sort(key=lambda item: -item[0])
    return [
        Hotspot(
            path=life.path,
            touches=life.touches,
            lines=lines,
            last_changed=commits[min(row for row, _, _ in life.events)].date.isoformat(),
            commits=[commits[row].hash for row in sorted(row for row, _, _ in life.events)[:TOP]],
        )
        for _, life, lines in scored[:TOP]
    ]


def _is_code(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() not in _NOT_CODE and not _TEST.search(path)


def _couplings(
    commits: Sequence[RawCommit], lives: Sequence[Life], touched: Sequence[Sequence[int]]
) -> list[Coupling]:
    """Pairs of code files in different folders that nearly always change in the same commit."""
    code = {i for i, life in enumerate(lives) if life.alive and _is_code(life.path)}
    together: Counter[tuple[int, int]] = Counter()
    where: dict[tuple[int, int], list[int]] = {}
    for row, ids in enumerate(touched):
        if not 2 <= len(ids) <= MAX_FILES_FOR_PAIRS:
            continue
        for pair in combinations(sorted(i for i in ids if i in code), 2):
            together[pair] += 1
            where.setdefault(pair, []).append(row)
    found: list[tuple[float, Coupling]] = []
    for (a, b), count in together.items():
        if count < MIN_TOGETHER:
            continue
        first, second = sorted((lives[a], lives[b]), key=lambda life: life.path)
        if PurePosixPath(first.path).parent == PurePosixPath(second.path).parent:
            continue
        share = count / (first.touches + second.touches - count)
        if share >= MIN_SHARE:
            coupling = Coupling(
                a=first.path,
                b=second.path,
                together=count,
                a_touches=first.touches,
                b_touches=second.touches,
                share=round(share, 3),
                commits=[commits[row].hash for row in sorted(where[(a, b)])[:TOP]],
            )
            found.append((count * share, coupling))
    found.sort(key=lambda item: (-item[0], item[1].a, item[1].b))
    return [coupling for _, coupling in found[:TOP]]


def _one_person_areas(commits: Sequence[RawCommit]) -> list[OnePersonArea]:
    """Parts of the repository where one person made nearly every change. Only meaningful
    when more than one person works on the repository."""
    people = {c.author for c in commits if not c.author.endswith("[bot]")}
    if len(people) < 2:
        return []
    by_area: dict[str, Counter[str]] = {}
    for commit in commits:
        if commit.is_merge or commit.author.endswith("[bot]"):
            continue
        for change in commit.changes:
            by_area.setdefault(area(change.path), Counter())[commit.author] += 1
    found: list[OnePersonArea] = []
    for name, authors in by_area.items():
        total = sum(authors.values())
        share = authors.most_common(1)[0][1] / total
        if total >= MIN_AREA_TOUCHES and share >= ONE_PERSON_SHARE:
            found.append(OnePersonArea(path=name, touches=total, share=round(share, 3)))
    return sorted(found, key=lambda item: -item.touches)[:TOP]


def find(
    commits: Sequence[RawCommit],
    lives: Sequence[Life],
    touched: Sequence[Sequence[int]],
    lines_of: Callable[[str], int | None],
) -> Insights:
    rows = {commit.hash: row for row, commit in enumerate(commits)}
    notes = _commit_notes(commits, rows)
    chains: list[FixChain] = []
    for chain in _fix_chains(commits, rows, touched):
        start, fixes = chain[0], chain[1:]
        shared = set(touched[fixes[0]]) & set(touched[start])
        took = (commits[chain[-1]].date - commits[start].date).total_seconds() / 60
        chains.append(
            FixChain(
                commits=[commits[row].hash for row in chain],
                minutes=round(took),
                files=sorted(lives[i].path for i in shared)[:3],
            )
        )
        for number, row in enumerate(fixes, start=1):
            text = f"Quick fix {number} of {len(fixes)} after {commits[start].hash[:7]}"
            notes[row].append(Note(kind="fix", text=text, flagged=True))
    chains.sort(key=lambda item: (-len(item.commits), item.minutes))
    return Insights(
        notes=notes,
        hotspots=_hotspots(commits, lives, lines_of),
        couplings=_couplings(commits, lives, touched),
        fix_chains=chains[:TOP],
        one_person_areas=_one_person_areas(commits),
    )
