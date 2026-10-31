"""Files that runs read and write: uploads from the web UI, and each run's own folder.

Both live under one root that the API owns (a temporary folder unless ``MARGIN_API_FILES_DIR``
says otherwise). An upload is kept until it is older than the result TTL; a run's folder goes
when the run is forgotten. Files are only ever served from a run's own folder, by name.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import BaseModel

# a JSON Schema ``format`` an agent puts on an input field (``json_schema_extra``)
UPLOAD_FORMAT = "file-path"  # the UI offers to upload a file and fills in where it was saved
OUTPUT_FORMAT = "output-dir"  # left empty, the API fills in the run's own folder

_UNSAFE = re.compile(r"[^\w.\- ()]+")


class RunFile(BaseModel):
    name: str
    size: int


def safe_name(name: str) -> str:
    """A file name with no folders and no characters that mean something to a shell or OS."""
    base = re.split(r"[\\/]", name)[-1]
    cleaned = _UNSAFE.sub("_", base).strip(" .")[:120]
    return cleaned or "upload"


def fields_with_format(schema: dict[str, Any], fmt: str) -> list[str]:
    """Input fields whose schema (or one of its variants) has ``format: fmt``."""
    found = []
    for name, prop in (schema.get("properties") or {}).items():
        variants = [prop, *(prop.get("anyOf") or []), *(prop.get("oneOf") or [])]
        if any(isinstance(v, dict) and v.get("format") == fmt for v in variants):
            found.append(name)
    return found


class FileStore:
    def __init__(self, root: str | None = None) -> None:
        self._owned = root is None
        self.root = Path(root or tempfile.mkdtemp(prefix="margin-api-")).resolve()
        self.uploads = self.root / "uploads"
        self.runs = self.root / "runs"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.runs.mkdir(parents=True, exist_ok=True)

    def new_upload(self, name: str) -> Path:
        """Where to save an upload: its own folder, so two files with one name never clash."""
        folder = self.uploads / uuid.uuid4().hex
        folder.mkdir()
        return folder / safe_name(name)

    def run_dir(self, run_id: str) -> Path:
        return self.runs / run_id

    def run_files(self, run_id: str) -> list[RunFile]:
        folder = self.run_dir(run_id)
        if not folder.is_dir():
            return []
        return [
            RunFile(name=p.name, size=p.stat().st_size)
            for p in sorted(folder.iterdir())
            if p.is_file()
        ]

    def run_file(self, run_id: str, name: str) -> Path | None:
        """A file a run wrote, or None. Only plain names inside the run's own folder."""
        if name != safe_name(name):
            return None
        folder = self.run_dir(run_id).resolve()
        path = (folder / name).resolve()
        return path if path.parent == folder and path.is_file() else None

    def forget_run(self, run_id: str) -> None:
        shutil.rmtree(self.run_dir(run_id), ignore_errors=True)

    def sweep_uploads(self, max_age_s: float) -> int:
        """Delete uploads older than ``max_age_s``. Returns how many were removed."""
        cutoff = time.time() - max_age_s
        removed = 0
        for folder in self.uploads.iterdir():
            try:
                if folder.stat().st_mtime < cutoff:
                    shutil.rmtree(folder, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
        return removed

    def close(self) -> None:
        """Remove the root if the API made it (a folder it was given is left in place)."""
        if self._owned:
            shutil.rmtree(self.root, ignore_errors=True)
