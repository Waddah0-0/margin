"""Words in column names and safe output file names."""

from __future__ import annotations

import re

ID_TOKENS = frozenset(
    {"id", "key", "code", "uuid", "guid", "sku", "no", "num", "number", "ref", "reference"}
)
UNSAFE_IN_NAME = re.compile(r"[^\w.\- ()]+")
_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}
)


def tokens(name: str) -> list[str]:
    """Words in a column name: ``orderDate``, ``order_date`` and ``Order Date`` all give
    ``["order", "date"]``."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    return [t for t in re.split(r"[^0-9A-Za-z؀-ۿ]+", spaced.lower()) if t]


def id_like(name: str) -> bool:
    return bool(set(tokens(name)) & ID_TOKENS)


def safe_name(text: str, *, max_len: int = 80, strip_double_dot: bool = False) -> str:
    """Part of a file name: no folders, OS-reserved names, or unsafe characters."""
    cleaned = UNSAFE_IN_NAME.sub("_", text).strip(" .")
    if strip_double_dot:
        while ".." in cleaned:
            cleaned = cleaned.replace("..", "_")
        cleaned = cleaned.strip(" .")
    cleaned = cleaned[:max_len].strip(" .")
    if cleaned.split(".")[0].rstrip().upper() in _DEVICES:
        cleaned = "_" + cleaned
    return cleaned or "table"
