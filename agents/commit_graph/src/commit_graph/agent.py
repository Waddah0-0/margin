"""Commit Graph: draws a repository's history as its tree and tells the story in it."""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path

from margin_core import AgentResult, BaseAgent, InvalidTargetError, RunContext
from margin_core.loaders.base import Workspace

from commit_graph import chapters as chaptering
from commit_graph import files as filing
from commit_graph import history, insights, marks, poster, report, write
from commit_graph.layout import lay_out
from commit_graph.models import (
    AiMark,
    Area,
    Chapter,
    Commit,
    CommitGraphInput,
    CommitGraphOutput,
    Edge,
    FileEvent,
    FileLife,
    Note,
    RepoInfo,
)

FILES_PER_COMMIT = 8
MAX_FILE_LIVES = 300
MAX_LINES_BYTES = 1_000_000


def _repo_name(target: str, root: Path) -> str:
    if "://" in target or target.startswith("github.com"):
        name = target.rstrip("/").rsplit("/", 1)[-1]
        return history.clean(name.removesuffix(".git"), 80) or "repository"
    return history.clean(root.name, 80) or "repository"


def _line_counter(ws: Workspace, prefix: str):  # type: ignore[no-untyped-def]
    """Lines in a file margin analyses, by its path in the repository. ``None`` for a file it
    leaves out (generated, vendored, binary, too large) or that is outside the workspace."""

    def lines_of(path: str) -> int | None:
        if prefix:
            if not path.startswith(prefix + "/"):
                return None
            path = path[len(prefix) + 1 :]
        info = ws.get_file(path)
        if info is None or info.is_generated or info.is_vendored:
            return None
        try:
            return len(ws.read_text(info, max_bytes=MAX_LINES_BYTES).splitlines())
        except (OSError, UnicodeError):
            return None

    return lines_of


class CommitGraphAgent(BaseAgent):
    id = "commit-graph"
    name = "Commit Graph"
    description = (
        "Draws a repository's history as its tree and tells the story in it: chapters, notes "
        "beside the commits, and the files that keep changing."
    )
    version = "0.1.0"
    InputModel = CommitGraphInput
    OutputModel = CommitGraphOutput
    primary_input = "target"
    uses_llm = True  # to write the chapters; the graph and the findings never call a model

    async def run(self, input: CommitGraphInput, ctx: RunContext) -> AgentResult:
        async with await ctx.load_workspace(
            input.target, paths=input.paths, branch=input.branch
        ) as ws:
            if ws.git is None:
                raise InvalidTargetError(f"{input.target} is not a git repository.")
            git = ws.git
            name = _repo_name(input.target, git.root)
            if git.head is None:
                empty = CommitGraphOutput(
                    repo=RepoInfo(
                        name=name, branch=git.branch, total_commits=0, shown=0, truncated=False
                    )
                )
                return self.make_result(summary=report.summary(empty), output=empty)

            ctx.report_progress("history", "Reading the history", 0.15)
            similar = not await asyncio.to_thread(history.is_partial_clone, git.root)
            total, raw = await asyncio.gather(
                asyncio.to_thread(history.count_commits, git.root, git.head, git.pathspecs),
                asyncio.to_thread(
                    history.read_history,
                    git.root,
                    git.head,
                    git.pathspecs,
                    input.max_commits,
                    similar,
                ),
            )
            ctx.check_cancelled()

            ctx.report_progress("graph", "Laying out the tree", 0.45)
            placed, lanes = lay_out(raw)
            lives, touched = filing.follow(raw)
            found = insights.find(raw, lives, touched, _line_counter(ws, git.prefix))
            facts = chaptering.split(raw)
        ctx.check_cancelled()

        ctx.report_progress("chapters", "Writing the chapters", 0.65)
        hashes = {commit.hash[:7]: commit.hash for commit in raw}
        llm = ctx.llm if input.write_with_model else None
        written = await write.write(facts, hashes, llm, ctx.warn)

        chapter_of = [0] * len(raw)
        chapters: list[Chapter] = []
        for fact, (title, parts, who) in zip(facts, written, strict=True):
            for row in range(fact.first_row, fact.last_row + 1):
                chapter_of[row] = fact.index
            chapters.append(
                Chapter(
                    index=fact.index,
                    title=title,
                    summary=parts,
                    written_by="model" if who == "model" else "template",
                    start=fact.start.isoformat(),
                    end=fact.end.isoformat(),
                    first_row=fact.first_row,
                    last_row=fact.last_row,
                    commits=fact.commits,
                    merges=fact.merges,
                    areas=[Area(path=path, share=round(share, 3)) for path, share in fact.areas],
                    tags=fact.tags,
                )
            )

        commits: list[Commit] = []
        tools_seen: dict[str, list[int]] = {}
        for row, (commit, place) in enumerate(zip(raw, placed, strict=True)):
            tools = marks.tools_in(commit)
            notes = list(found.notes[row])
            for tool in tools:
                tools_seen.setdefault(tool, []).append(row)
                notes.append(Note(kind="ai", text=f"Marked as made with {tool}"))
            commits.append(
                Commit(
                    hash=commit.hash,
                    short=commit.hash[:7],
                    parents=commit.parents,
                    lane=place.lane,
                    edges=[Edge(to=parent, lane=lane) for parent, lane in place.edges],
                    author=commit.author,
                    date=commit.date.isoformat(),
                    subject=commit.subject,
                    tags=commit.tags,
                    branches=commit.branches,
                    files_changed=len(commit.changes),
                    files=[change.path for change in commit.changes[:FILES_PER_COMMIT]],
                    chapter=chapter_of[row],
                    notes=notes,
                    ai_tools=tools,
                )
            )

        busiest = sorted(
            (life for life in lives if life.touches >= 2), key=lambda life: -life.touches
        )[:MAX_FILE_LIVES]
        people = Counter(c.author for c in raw if not c.author.endswith("[bot]"))
        output = CommitGraphOutput(
            repo=RepoInfo(
                name=name,
                branch=git.branch,
                head=git.head,
                total_commits=max(total, len(raw)),
                shown=len(raw),
                truncated=total > len(raw),
                first_date=min(c.date for c in raw).isoformat() if raw else None,
                last_date=max(c.date for c in raw).isoformat() if raw else None,
                authors=len(people),
                lanes=lanes,
                renames_followed="similar" if similar else "exact",
            ),
            commits=commits,
            chapters=chapters,
            hotspots=found.hotspots,
            couplings=found.couplings,
            fix_chains=found.fix_chains,
            one_person_areas=found.one_person_areas,
            files=[
                FileLife(
                    path=life.path,
                    alive=life.alive,
                    touches=life.touches,
                    events=[
                        FileEvent(row=row, kind=kind, was=was)  # type: ignore[arg-type]
                        for row, kind, was in sorted(life.events)
                    ],
                )
                for life in busiest
            ],
            ai_marks=sorted(
                (
                    AiMark(
                        tool=tool,
                        commits=len(rows),
                        first_seen=raw[max(rows)].date.isoformat(),
                        first_commit=raw[max(rows)].hash,
                    )
                    for tool, rows in tools_seen.items()
                ),
                key=lambda mark: mark.first_seen,
            ),
        )
        if input.output_dir:
            ctx.report_progress("poster", "Drawing the poster", 0.9)
            output.poster = await asyncio.to_thread(
                poster.write_poster, output, Path(input.output_dir)
            )
        ctx.report_progress("done", "Finished", 1.0)
        return self.make_result(
            summary=report.summary(output), output=output, findings=report.findings(output)
        )
