"""Marks that AI tools leave in commit messages. They are reported as they are found and
never scored: a mark says a tool was used on that commit, not how much of it the tool wrote."""

from __future__ import annotations

import re

from commit_graph.history import RawCommit

_CO = r"co-authored-by:[^\n]*"
_TOOLS: list[tuple[str, re.Pattern[str]]] = [
    (
        "Claude",
        re.compile(rf"{_CO}\bclaude\b|generated with \[?claude code|^claude\[bot\]$", re.I | re.M),
    ),
    ("GitHub Copilot", re.compile(rf"{_CO}\bcopilot\b|^copilot(-swe-agent)?\[bot\]$", re.I | re.M)),
    (
        "Cursor",
        re.compile(rf"{_CO}\bcursor ?agent\b|{_CO}@cursor\.com|^cursor\[bot\]$", re.I | re.M),
    ),
    ("Aider", re.compile(rf"{_CO}\baider\b|\(aider\)$", re.I | re.M)),
    ("Codex", re.compile(rf"{_CO}\bcodex\b|^chatgpt-codex-connector\[bot\]$", re.I | re.M)),
    ("Gemini", re.compile(rf"{_CO}\bgemini\b|^gemini-cli\[bot\]$", re.I | re.M)),
    ("Devin", re.compile(rf"{_CO}\bdevin\b|^devin-ai-integration\[bot\]$", re.I | re.M)),
    ("Jules", re.compile(r"^google-labs-jules\[bot\]$", re.I | re.M)),
]


def tools_in(commit: RawCommit) -> list[str]:
    """The AI tools that marked this commit, by its message trailers or its author name."""
    text = f"{commit.author}\n{commit.body}"
    return [tool for tool, pattern in _TOOLS if pattern.search(text)]
