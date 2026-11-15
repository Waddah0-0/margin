"""Input and output models of the Commit Graph."""

from __future__ import annotations

from typing import Literal

from margin_core import AgentInput
from pydantic import BaseModel, Field

DEFAULT_MAX_COMMITS = 500
MAX_COMMITS = 3000


class CommitGraphInput(AgentInput):
    target: str = Field(
        min_length=1,
        description="GitHub URL (https://github.com/<owner>/<repo>) or local path.",
        examples=["https://github.com/psf/requests"],
    )
    branch: str | None = Field(
        default=None, description="Branch to read (GitHub targets). Default: the main branch."
    )
    paths: list[str] = Field(
        default_factory=list,
        description="Only the history of these folders or files. Empty: the whole repository.",
    )
    max_commits: int = Field(
        default=DEFAULT_MAX_COMMITS,
        ge=1,
        le=MAX_COMMITS,
        description="How many commits to draw, counted back from the newest.",
    )
    write_with_model: bool = Field(
        default=True,
        description="Let the model write the chapter titles and summaries. Without a model "
        "they are written from a template.",
    )
    output_dir: str | None = Field(
        default=None,
        description="Folder for the poster (SVG). Nothing is written when empty; in the web "
        "UI, the poster is offered for download.",
        # margin-api fills in a folder of the run's own and serves the files from it
        json_schema_extra={"format": "output-dir"},
    )


class Edge(BaseModel):
    """The line from a commit down to one parent. It runs in ``lane`` until the parent's row."""

    to: str
    lane: int


class Note(BaseModel):
    """A note in the margin, level with the commit it is about."""

    kind: Literal["root", "merge", "big", "revert", "gap", "fix", "ai"]
    text: str
    flagged: bool = False


class Commit(BaseModel):
    hash: str
    short: str
    parents: list[str]
    lane: int
    edges: list[Edge]
    author: str
    date: str = Field(description="When it was written (ISO 8601).")
    subject: str
    tags: list[str] = Field(default_factory=list)
    branches: list[str] = Field(default_factory=list)
    files_changed: int = 0
    files: list[str] = Field(default_factory=list, description="The first few changed paths.")
    chapter: int = 0
    notes: list[Note] = Field(default_factory=list)
    ai_tools: list[str] = Field(default_factory=list)


class Area(BaseModel):
    path: str
    share: float = Field(description="Share of the chapter's file changes, 0 to 1.")


class TextPart(BaseModel):
    """A piece of chapter text. ``commit`` is set when the piece cites a commit."""

    text: str
    commit: str | None = None


class Chapter(BaseModel):
    index: int
    title: str
    summary: list[TextPart]
    written_by: Literal["model", "template"] = "template"
    start: str
    end: str
    first_row: int = Field(description="Row of its newest commit.")
    last_row: int = Field(description="Row of its oldest commit.")
    commits: int
    merges: int
    areas: list[Area] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class Hotspot(BaseModel):
    path: str
    touches: int
    lines: int | None = None
    last_changed: str
    commits: list[str] = Field(default_factory=list, description="The latest few, as hashes.")


class Coupling(BaseModel):
    a: str
    b: str
    together: int
    a_touches: int
    b_touches: int
    share: float = Field(description="Commits with both, out of commits with either.")
    commits: list[str] = Field(default_factory=list)


class FixChain(BaseModel):
    commits: list[str] = Field(description="The first commit, then each quick fix after it.")
    minutes: int
    files: list[str] = Field(default_factory=list)


class OnePersonArea(BaseModel):
    path: str
    touches: int
    share: float = Field(description="Share of the changes made by one person.")


class FileEvent(BaseModel):
    row: int
    kind: Literal["added", "changed", "renamed", "deleted"]
    was: str | None = Field(default=None, description="The old path, for a rename.")


class FileLife(BaseModel):
    path: str
    alive: bool
    touches: int
    events: list[FileEvent]


class AiMark(BaseModel):
    tool: str
    commits: int
    first_seen: str
    first_commit: str


class RepoInfo(BaseModel):
    name: str
    branch: str | None = None
    head: str | None = None
    total_commits: int
    shown: int
    truncated: bool
    first_date: str | None = None
    last_date: str | None = None
    authors: int = 0
    lanes: int = 1
    renames_followed: Literal["exact", "similar"] = "exact"


class CommitGraphOutput(BaseModel):
    repo: RepoInfo
    commits: list[Commit] = Field(default_factory=list)
    chapters: list[Chapter] = Field(default_factory=list)
    hotspots: list[Hotspot] = Field(default_factory=list)
    couplings: list[Coupling] = Field(default_factory=list)
    fix_chains: list[FixChain] = Field(default_factory=list)
    one_person_areas: list[OnePersonArea] = Field(default_factory=list)
    files: list[FileLife] = Field(default_factory=list)
    ai_marks: list[AiMark] = Field(default_factory=list)
    poster: str | None = Field(default=None, description="File name of the poster, if written.")
