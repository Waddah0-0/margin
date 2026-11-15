"""Splits the history into chapters: a tag ends one, and so does a long quiet gap."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median

from commit_graph.history import RawCommit

MAX_CHAPTERS = 10
MIN_COMMITS = 3
MIN_GAP_DAYS = 3.0
SUBJECTS_PER_CHAPTER = 14
_TAG_SCORE = 1e6


@dataclass
class ChapterFacts:
    index: int  # 1 is the oldest
    first_row: int  # its newest commit
    last_row: int  # its oldest commit
    start: datetime
    end: datetime
    commits: int
    merges: int
    has_root: bool
    areas: list[tuple[str, float]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    subjects: list[tuple[str, str]] = field(default_factory=list)  # (short hash, subject)

    @property
    def days(self) -> int:
        return max(1, (self.end - self.start).days + 1)


def area(path: str) -> str:
    """The part of the repository a path belongs to: its first two folders."""
    parts = path.split("/")
    if len(parts) == 1:
        return "top-level files"
    return "/".join(parts[: min(2, len(parts) - 1)]) + "/"


def _boundaries(chron: Sequence[RawCommit]) -> list[int]:
    """Indexes in ``chron`` (oldest first) where a new chapter starts."""
    count = len(chron)
    gaps = [
        max(0.0, (chron[i].date - chron[i - 1].date).total_seconds() / 86400)
        for i in range(1, count)
    ]
    positive = [gap for gap in gaps if gap > 0]
    threshold = max(MIN_GAP_DAYS, 5 * median(positive)) if positive else MIN_GAP_DAYS
    scored: list[tuple[float, int]] = []
    for i in range(1, count):
        gap = gaps[i - 1]
        if chron[i - 1].tags:
            scored.append((_TAG_SCORE + gap, i))
        elif gap >= threshold:
            scored.append((gap, i))
    chosen: list[int] = []
    for _, i in sorted(scored, reverse=True):
        if len(chosen) == MAX_CHAPTERS - 1:
            break
        if i < MIN_COMMITS or count - i < MIN_COMMITS:
            continue
        if all(abs(i - other) >= MIN_COMMITS for other in chosen):
            chosen.append(i)
    return sorted(chosen)


def split(commits: Sequence[RawCommit]) -> list[ChapterFacts]:
    """Chapters, oldest first. ``commits`` come newest first, as they are drawn."""
    if not commits:
        return []
    count = len(commits)
    chron = list(reversed(commits))
    starts = [0, *_boundaries(chron), count]
    chapters: list[ChapterFacts] = []
    for index, (begin, end) in enumerate(zip(starts, starts[1:], strict=False), start=1):
        part = chron[begin:end]
        touched: Counter[str] = Counter()
        for commit in part:
            if not commit.is_merge:
                touched.update(area(change.path) for change in commit.changes)
        total = sum(touched.values())
        plain = [c for c in part if not c.is_merge] or part
        step = max(1, len(plain) // SUBJECTS_PER_CHAPTER)
        chapters.append(
            ChapterFacts(
                index=index,
                first_row=count - end,
                last_row=count - 1 - begin,
                start=min(c.date for c in part),
                end=max(c.date for c in part),
                commits=len(part),
                merges=sum(1 for c in part if c.is_merge),
                has_root=any(not c.parents for c in part),
                areas=[(name, n / total) for name, n in touched.most_common(3)] if total else [],
                tags=[tag for c in part for tag in c.tags],
                subjects=[(c.hash[:7], c.subject) for c in plain[::step]][:SUBJECTS_PER_CHAPTER],
            )
        )
    return chapters
