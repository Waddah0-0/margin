"""Turns the output into the summary and the findings every margin agent returns."""

from __future__ import annotations

from datetime import datetime

from margin_core import Evidence, Finding

from commit_graph.insights import plural
from commit_graph.models import CommitGraphOutput


def _day(iso: str) -> str:
    when = datetime.fromisoformat(iso)
    return f"{when.day} {when:%b %Y}"


def summary(output: CommitGraphOutput) -> str:
    repo = output.repo
    if not repo.shown:
        return "This repository has no commits yet."
    text = plural(repo.shown, "commit")
    if repo.truncated:
        text = f"The newest {repo.shown} of {repo.total_commits} commits"
    if repo.first_date and repo.last_date:
        text += f", from {_day(repo.first_date)} to {_day(repo.last_date)}"
    text += f", in {plural(len(output.chapters), 'chapter')}."
    found = [
        (len(output.hotspots), "hotspot", "hotspots"),
        (
            len(output.couplings),
            "pair of files that change together",
            "pairs of files that change together",
        ),
        (len(output.fix_chains), "run of quick fixes", "runs of quick fixes"),
        (len(output.one_person_areas), "area with one author", "areas with one author"),
    ]
    named = [f"{count} {one if count == 1 else many}" for count, one, many in found if count]
    if named:
        text += " Found " + ", ".join(named) + "."
    return text


def findings(output: CommitGraphOutput) -> list[Finding]:
    found: list[Finding] = []
    if output.hotspots:
        found.append(
            Finding(
                title="Files that change the most",
                summary="Large files that keep changing are where bugs tend to be. These are "
                "worth the most care in review, and are the first to consider splitting.",
                evidence=[
                    Evidence(
                        kind="file",
                        location=spot.path,
                        detail=f"Changed in {plural(spot.touches, 'commit')}"
                        + (f"; {plural(spot.lines, 'line')} long" if spot.lines else "")
                        + f". Last changed {_day(spot.last_changed)}.",
                    )
                    for spot in output.hotspots
                ],
            )
        )
    if output.couplings:
        found.append(
            Finding(
                title="Files that change together",
                summary="These files are in different folders but nearly always change in the "
                "same commit, so a change to one probably needs the other.",
                evidence=[
                    Evidence(
                        kind="file",
                        location=f"{pair.a} + {pair.b}",
                        detail=f"Changed together in {pair.together} of the "
                        f"{pair.a_touches + pair.b_touches - pair.together} commits that "
                        "changed either.",
                    )
                    for pair in output.couplings
                ],
            )
        )
    if output.fix_chains:
        found.append(
            Finding(
                title="Runs of quick fixes",
                summary="A commit followed within the hour by fix after fix to the same files. "
                "It often means the change went in before it was tested.",
                evidence=[
                    Evidence(
                        kind="commit",
                        location=chain.commits[0][:7],
                        detail=f"Followed by {len(chain.commits) - 1} fixes "
                        f"within {plural(chain.minutes, 'minute')}"
                        + (f", in {', '.join(chain.files)}" if chain.files else "")
                        + ".",
                    )
                    for chain in output.fix_chains
                ],
            )
        )
    if output.one_person_areas:
        found.append(
            Finding(
                title="Areas with one author",
                summary="Nearly every change in these parts was made by the same person. If "
                "that person is away, nobody else has worked on them.",
                evidence=[
                    Evidence(
                        kind="metric",
                        location=area.path,
                        detail=f"One person made {area.share:.0%} of {area.touches} file changes.",
                    )
                    for area in output.one_person_areas
                ],
            )
        )
    if output.ai_marks:
        found.append(
            Finding(
                title="AI tool marks",
                summary="Commits whose message says an AI tool took part. A mark is reported "
                "as it is found and is not a score: it does not say how much the tool wrote.",
                evidence=[
                    Evidence(
                        kind="commit",
                        location=mark.first_commit[:7],
                        detail=f"{mark.tool}: {plural(mark.commits, 'commit')}, first on "
                        f"{_day(mark.first_seen)}.",
                    )
                    for mark in output.ai_marks
                ],
            )
        )
    return found
