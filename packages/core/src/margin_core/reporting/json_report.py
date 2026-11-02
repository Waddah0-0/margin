"""Render an :class:`AgentResult` as JSON."""

from __future__ import annotations

import re
from pathlib import Path

from margin_core.models import AgentResult


def to_json(result: AgentResult, *, indent: int | None = 2) -> str:
    # pydantic escapes characters below 0x20; these reach a terminal as they are
    return re.sub(
        r"[\x7f-\x9f]", lambda m: f"\\u{ord(m[0]):04x}", result.model_dump_json(indent=indent)
    )


def write_json(result: AgentResult, path: str | Path, *, indent: int | None = 2) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_json(result, indent=indent) + "\n", encoding="utf-8")
    return out
