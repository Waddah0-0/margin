"""Follows each file through the history: added, changed, renamed, deleted."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from commit_graph.history import RawCommit

_KINDS = {"A": "added", "M": "changed", "D": "deleted", "R": "renamed"}


@dataclass
class Life:
    path: str  # its latest name
    alive: bool = True
    events: list[tuple[int, str, str | None]] = field(default_factory=list)  # row, kind, old path

    @property
    def touches(self) -> int:
        return len(self.events)


def follow(commits: Sequence[RawCommit]) -> tuple[list[Life], list[list[int]]]:
    """Return every file's life, and for each row the files (by index) that commit touched.

    Merge commits are skipped: what they bring in was already counted on its own branch.
    A file first seen as changed or renamed was there before the oldest commit shown.
    """
    lives: list[Life] = []
    current: dict[str, int] = {}
    touched: list[list[int]] = [[] for _ in commits]

    def life_at(path: str) -> int:
        if path not in current:
            lives.append(Life(path=path))
            current[path] = len(lives) - 1
        return current[path]

    for row in range(len(commits) - 1, -1, -1):
        commit = commits[row]
        if commit.is_merge:
            continue
        seen: list[int] = []
        for change in commit.changes:
            if change.status == "R" and change.old is not None:
                index = life_at(change.old)
                del current[change.old]
                current[change.path] = index
                lives[index].path = change.path
                lives[index].events.append((row, "renamed", change.old))
            else:
                index = life_at(change.path)
                lives[index].events.append((row, _KINDS[change.status], None))
                if change.status == "D":
                    lives[index].alive = False
                    del current[change.path]
                else:
                    lives[index].alive = True
            if index not in seen:
                seen.append(index)
        touched[row] = seen
    return lives, touched
