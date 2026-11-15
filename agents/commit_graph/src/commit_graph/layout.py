"""Gives every commit a lane, and every line to a parent a lane to run in.

The commits come newest first with children before parents. Going down the rows, each lane
remembers which commit it is waiting for. A commit takes the first lane waiting for it (other
lanes waiting for it end there), or a free lane when it is the tip of something. Its first
parent continues in the same lane; each further parent gets the lane already waiting for that
parent, or a free one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from commit_graph.history import RawCommit


@dataclass
class Placed:
    lane: int
    edges: list[tuple[str, int]]  # (parent hash, lane the line runs in)


def lay_out(commits: Sequence[RawCommit]) -> tuple[list[Placed], int]:
    """Return a placement per commit, and how many lanes the widest row needs."""
    waiting: list[str | None] = []
    placed: list[Placed] = []
    width = 1

    def free_lane() -> int:
        for index, value in enumerate(waiting):
            if value is None:
                return index
        waiting.append(None)
        return len(waiting) - 1

    for commit in commits:
        mine = [index for index, value in enumerate(waiting) if value == commit.hash]
        if mine:
            lane = mine[0]
            for other in mine[1:]:
                waiting[other] = None
        else:
            lane = free_lane()
        waiting[lane] = None

        edges: list[tuple[str, int]] = []
        for position, parent in enumerate(commit.parents):
            if position == 0:
                waiting[lane] = parent
                edges.append((parent, lane))
            elif parent in waiting:
                edges.append((parent, waiting.index(parent)))
            else:
                target = free_lane()
                waiting[target] = parent
                edges.append((parent, target))

        width = max(width, len(waiting))
        while waiting and waiting[-1] is None:
            waiting.pop()
        placed.append(Placed(lane=lane, edges=edges))
    return placed, width
