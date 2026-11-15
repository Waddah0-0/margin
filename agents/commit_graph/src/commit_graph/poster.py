"""Draws the history as one SVG: the tree, with each chapter's title in the margin."""

from __future__ import annotations

import re
import textwrap
from datetime import datetime
from html import escape
from pathlib import Path

from commit_graph.models import Chapter, Commit, CommitGraphOutput

WIDTH = 900
TOP = 96
MARGIN_W = 250
LINE_X = MARGIN_W + 12
GRAPH_X = LINE_X + 22
LANE = 10
PAPER, INK, QUIET, RULE, RED = "#f5f5f1", "#141413", "#6e6e67", "#d8d8cf", "#c8321f"
_DEVICES = re.compile(r"^(con|prn|aux|nul|com\d|lpt\d)$", re.I)


def safe_stem(name: str) -> str:
    """A file name made from a repository name: no folders, no special characters, and not a
    Windows device."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")[:60] or "history"
    return f"_{stem}" if _DEVICES.match(stem.split(".")[0]) else stem


def _day(iso: str) -> str:
    when = datetime.fromisoformat(iso)
    return f"{when.day} {when:%b %Y}"


def _edge(x1: float, y1: float, lane_x: float, x2: float, y2: float, row_h: float) -> str:
    """From a commit down to its parent: into the line's lane, straight down, into the parent."""
    if y2 - y1 <= row_h + 0.01:
        return (
            f"M{x1:.1f} {y1:.1f} C{x1:.1f} {y1 + row_h / 2:.1f} "
            f"{x2:.1f} {y2 - row_h / 2:.1f} {x2:.1f} {y2:.1f}"
        )
    first, last = y1 + row_h, y2 - row_h
    return (
        f"M{x1:.1f} {y1:.1f} C{x1:.1f} {y1 + row_h / 2:.1f} {lane_x:.1f} {first - row_h / 2:.1f} "
        f"{lane_x:.1f} {first:.1f} L{lane_x:.1f} {last:.1f} "
        f"C{lane_x:.1f} {last + row_h / 2:.1f} {x2:.1f} {y2 - row_h / 2:.1f} {x2:.1f} {y2:.1f}"
    )


def _chapter_label(chapter: Chapter, y: float, room: float) -> list[str]:
    lines = textwrap.wrap(chapter.title, 36) or [chapter.title]
    fit = max(1, int((room - 14) // 14))
    if len(lines) > fit:
        lines = lines[:fit]
        lines[-1] = lines[-1][:34].rstrip() + "…"
    out = [
        f'<text x="{MARGIN_W}" y="{y + 14 * i:.1f}" text-anchor="end" font-size="11.5" '
        f'font-weight="700" fill="{INK}">{escape(line)}</text>'
        for i, line in enumerate(lines)
    ]
    dates = _day(chapter.start)
    if _day(chapter.end) != dates:
        dates += f" to {_day(chapter.end)}"
    if room >= 14 * (len(lines) + 1):  # a short chapter has no room for its dates
        out.append(
            f'<text x="{MARGIN_W}" y="{y + 14 * len(lines):.1f}" text-anchor="end" '
            f'font-size="9.5" fill="{QUIET}">{escape(dates)}</text>'
        )
    return out


def draw(output: CommitGraphOutput) -> str:
    commits = output.commits
    row_h = 10.0 if len(commits) <= 800 else 6.0
    height = TOP + len(commits) * row_h + 48
    rows = {commit.hash: row for row, commit in enumerate(commits)}

    def x(lane: int) -> float:
        return GRAPH_X + lane * LANE

    def y(row: float) -> float:
        return TOP + row * row_h + row_h / 2

    label_x = x(output.repo.lanes) + 10
    span = ""
    if output.repo.first_date and output.repo.last_date:
        span = f", {_day(output.repo.first_date)} to {_day(output.repo.last_date)}"
    count = f"{output.repo.shown} commits"
    if output.repo.truncated:
        count = f"The newest {output.repo.shown} of {output.repo.total_commits} commits"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height:.0f}" '
        f'viewBox="0 0 {WIDTH} {height:.0f}" font-family="Archivo, Helvetica, Arial, sans-serif">',
        f'<rect width="100%" height="100%" fill="{PAPER}"/>',
        f'<text x="{GRAPH_X - 6}" y="44" font-size="26" font-weight="700" fill="{INK}">'
        f"{escape(output.repo.name)}</text>",
        f'<text x="{GRAPH_X - 6}" y="66" font-size="12" fill="{QUIET}">'
        f"{escape(count + span)}</text>",
        f'<line x1="{LINE_X}" y1="{TOP - 12}" x2="{LINE_X}" y2="{height - 24:.0f}" '
        f'stroke="{RED}" stroke-opacity="0.5"/>',
    ]
    for chapter in output.chapters:
        top = TOP + chapter.first_row * row_h
        parts.append(
            f'<line x1="{LINE_X + 8}" y1="{top:.1f}" x2="{WIDTH - 24}" y2="{top:.1f}" '
            f'stroke="{RULE}"/>'
        )
        room = (chapter.last_row - chapter.first_row + 1) * row_h
        parts += _chapter_label(chapter, top + 13, room)
        about = f"{chapter.commits} commits" if chapter.commits != 1 else "1 commit"
        if chapter.areas:
            about += " · " + ", ".join(area.path for area in chapter.areas[:2])
        parts.append(
            f'<text x="{WIDTH - 24}" y="{top + 13:.1f}" text-anchor="end" font-size="9.5" '
            f'fill="{QUIET}">{escape(about)}</text>'
        )

    edges: list[str] = []
    dots: list[str] = []
    for row, commit in enumerate(commits):
        for edge in commit.edges:
            parent = rows.get(edge.to)
            if parent is None:  # the parent is older than the oldest commit drawn
                end_row, end_lane = float(len(commits)), edge.lane
            else:
                end_row, end_lane = float(parent), commits[parent].lane
            edges.append(
                _edge(x(commit.lane), y(row), x(edge.lane), x(end_lane), y(end_row), row_h)
            )
        dots.append(_dot(commit, x(commit.lane), y(row), row_h))
        if commit.tags:
            parts.append(
                f'<text x="{label_x:.1f}" y="{y(row) + 3:.1f}" font-size="9" fill="{INK}" '
                f'font-family="JetBrains Mono, Consolas, monospace">'
                f"{escape(', '.join(commit.tags))}</text>"
            )
    parts.append(f'<path d="{" ".join(edges)}" fill="none" stroke="{QUIET}" stroke-width="1"/>')
    parts += dots
    parts.append("</svg>")
    return "\n".join(parts)


def _dot(commit: Commit, cx: float, cy: float, row_h: float) -> str:
    radius = 2.6 if row_h >= 10 else 1.8
    flagged = any(note.flagged for note in commit.notes)
    colour = RED if flagged else INK
    if len(commit.parents) > 1:
        return (
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius}" fill="{PAPER}" stroke="{colour}"/>'
        )
    return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius}" fill="{colour}"/>'


def write_poster(output: CommitGraphOutput, folder: Path) -> str:
    """Write the poster into ``folder`` and return its file name."""
    folder.mkdir(parents=True, exist_ok=True)
    name = f"{safe_stem(output.repo.name)}.history.svg"
    (folder / name).write_text(draw(output), encoding="utf-8")
    return name
