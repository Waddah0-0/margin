from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from commit_graph import CommitGraphAgent, chapters, files, insights, marks, poster, write
from commit_graph.history import Change, RawCommit, parse_history
from commit_graph.layout import lay_out
from margin_core.llm.mock import MockLLM

START = datetime(2025, 1, 1, 12, tzinfo=UTC)


def commit(
    sha: str,
    parents: list[str],
    *,
    hours: float = 0,
    subject: str = "work",
    author: str = "Ada",
    changes: list[Change] | None = None,
    tags: list[str] | None = None,
    body: str = "",
) -> RawCommit:
    return RawCommit(
        hash=sha.ljust(40, "0"),
        parents=[p.ljust(40, "0") for p in parents],
        author=author,
        date=START + timedelta(hours=hours),
        subject=subject,
        body=body,
        tags=tags or [],
        changes=changes if changes is not None else [Change("M", "src/a.py")],
    )


def line(count: int, **kwargs: object) -> list[RawCommit]:
    """A straight history of ``count`` commits, newest first, one hour apart."""
    made = [
        commit(f"c{i:03d}", [f"c{i - 1:03d}"] if i else [], hours=i, **kwargs)  # type: ignore[arg-type]
        for i in range(count)
    ]
    return made[::-1]


# ---- layout ---------------------------------------------------------------------------------


def test_a_straight_history_uses_one_lane() -> None:
    placed, width = lay_out(line(5))
    assert width == 1
    assert [p.lane for p in placed] == [0] * 5
    assert placed[-1].edges == []


def test_a_merged_branch_gets_its_own_lane_and_joins_back() -> None:
    history = [
        commit("m", ["a2", "b1"], hours=4),
        commit("b1", ["a1"], hours=3),
        commit("a2", ["a1"], hours=2),
        commit("a1", [], hours=1),
    ]
    placed, width = lay_out(history)
    assert width == 2
    assert [p.lane for p in placed] == [0, 1, 0, 0]
    assert [lane for _, lane in placed[0].edges] == [0, 1]
    # both lines end at a1, which sits in lane 0
    assert placed[1].edges[0][1] == 1
    assert placed[2].edges[0][1] == 0


def test_a_lane_is_reused_once_its_branch_has_ended() -> None:
    history = [
        commit("m2", ["m1", "y"], hours=7),
        commit("y", ["m1"], hours=6),
        commit("m1", ["a", "x"], hours=5),
        commit("x", ["a"], hours=4),
        commit("a", [], hours=1),
    ]
    placed, width = lay_out(history)
    assert width == 2
    assert placed[1].lane == 1 and placed[3].lane == 1


# ---- reading --------------------------------------------------------------------------------


def test_parse_history_reads_refs_changes_and_messages_with_odd_characters() -> None:
    record = (
        "\x1e" + "a" * 40 + "\x1f" + "b" * 40 + " " + "c" * 40 + "\x1fAda\x07 L\x1f"
        "2025-03-01T10:00:00+02:00\x1fHEAD -> main, tag: v1.0, origin/main, origin/HEAD\x1f"
        "added \x1b[31mthings\x1fbody line\n\nCo-authored-by: X\n\x1f\n"
        "M\tsrc/a.py\nA\tsrc/b.py\nR100\told.py\tnew.py\nD\tgone.py\nC75\tx.py\ty.py\n"
    )
    [parsed] = parse_history(record)
    assert parsed.parents == ["b" * 40, "c" * 40] and parsed.is_merge
    assert parsed.author == "Ada L" and "\x1b" not in parsed.subject
    assert parsed.tags == ["v1.0"] and parsed.branches == ["main", "origin/main"]
    assert [(c.status, c.path, c.old) for c in parsed.changes] == [
        ("M", "src/a.py", None),
        ("A", "src/b.py", None),
        ("R", "new.py", "old.py"),
        ("D", "gone.py", None),
        ("A", "y.py", None),
    ]


# ---- chapters -------------------------------------------------------------------------------


def test_a_tag_and_a_long_gap_each_end_a_chapter() -> None:
    history = line(12)
    chron = history[::-1]
    chron[3].tags = ["v1"]
    for later in chron[8:]:
        later.date += timedelta(days=30)
    found = chapters.split(history)
    assert [c.commits for c in found] == [4, 4, 4]
    assert found[0].has_root and found[0].tags == ["v1"]
    assert (found[0].last_row, found[0].first_row) == (11, 8)
    assert found[2].first_row == 0


def test_a_short_history_is_one_chapter() -> None:
    [only] = chapters.split(line(4))
    assert only.commits == 4 and only.areas == [("src/", 1.0)]


def test_area_names() -> None:
    assert chapters.area("README.md") == "top-level files"
    assert chapters.area("ui/App.tsx") == "ui/"
    assert chapters.area("packages/core/src/x.py") == "packages/core/"


# ---- files ----------------------------------------------------------------------------------


def test_a_file_is_followed_through_a_rename_and_a_delete() -> None:
    history = [
        commit("d", ["c"], hours=4, changes=[Change("D", "b.py")]),
        commit("c", ["b"], hours=3, changes=[Change("R", "b.py", "a.py")]),
        commit("b", ["a"], hours=2, changes=[Change("M", "a.py")]),
        commit("a", [], hours=1, changes=[Change("A", "a.py")]),
    ]
    lives, touched = files.follow(history)
    [life] = lives
    assert life.path == "b.py" and not life.alive
    assert [(row, kind) for row, kind, _ in life.events] == [
        (3, "added"),
        (2, "changed"),
        (1, "renamed"),
        (0, "deleted"),
    ]
    assert touched == [[0], [0], [0], [0]]


# ---- insights -------------------------------------------------------------------------------


def find(history: list[RawCommit], lines: int | None = 100) -> insights.Insights:
    lives, touched = files.follow(history)
    return insights.find(history, lives, touched, lambda _path: lines)


def test_notes_for_the_first_commit_a_merge_a_revert_and_a_quiet_gap() -> None:
    history = [
        commit("r", ["m"], hours=24 * 40, subject='Revert "work"'),
        commit("m", ["a2", "b2"], hours=80),
        commit("b2", ["b1"], hours=70),
        commit("b1", ["a1"], hours=20),
        commit("a2", ["a1"], hours=10),
        commit("a1", [], hours=1),
    ]
    notes = find(history).notes
    assert [n.kind for n in notes[5]] == ["root"]
    [merge] = notes[1]
    assert merge.text == "Merged a branch of 2 commits, 2 days after it started"
    assert {n.kind for n in notes[0]} == {"gap", "revert"}
    assert any(n.flagged for n in notes[0])


def test_a_branch_from_an_old_commit_is_not_a_quiet_spell() -> None:
    day = 24
    history = [
        commit("m", ["a3", "b1"], hours=31 * day),
        commit("b1", ["a1"], hours=30 * day + 12),
        commit("a3", ["a2"], hours=30 * day),
        commit("a2", ["a1"], hours=10 * day),
        commit("a1", [], hours=1),
    ]
    notes = find(history).notes
    assert [n.text for n in notes[2] if n.kind == "gap"] == ["After 20 quiet days"]
    assert not [n for n in notes[1] if n.kind == "gap"]


def test_two_quick_fixes_make_a_chain_and_one_does_not() -> None:
    history = [
        commit("f3", ["x"], hours=10.2, subject="fix typo"),
        commit("x", ["f2"], hours=10, subject="added y"),
        commit("f2", ["f1"], hours=1.5, subject="fixed it again"),
        commit("f1", ["a"], hours=1.2, subject="fix the thing"),
        commit("a", [], hours=1, subject="added the thing"),
    ]
    found = find(history)
    [chain] = found.fix_chains
    assert [h[:2] for h in chain.commits] == ["a0", "f1", "f2"]
    assert chain.minutes == 30 and chain.files == ["src/a.py"]
    assert [n.text for n in found.notes[2]] == ["Quick fix 2 of 2 after a000000"]
    assert found.notes[0] == []


def test_hotspots_need_enough_changes_and_a_file_margin_analyses() -> None:
    history = line(6)
    [spot] = find(history).hotspots
    assert (spot.path, spot.touches, spot.lines) == ("src/a.py", 6, 100)
    assert len(spot.commits) == 5
    assert find(history, lines=None).hotspots == []
    assert find(line(3)).hotspots == []


def test_files_in_different_folders_that_change_together_are_coupled() -> None:
    both = [Change("M", "api/routes.py"), Change("M", "ui/client.ts"), Change("M", "api/x.py")]
    history = line(6, changes=both)
    found = find(history).couplings
    assert [(c.a, c.b, c.together) for c in found] == [
        ("api/routes.py", "ui/client.ts", 6),
        ("api/x.py", "ui/client.ts", 6),
    ]
    assert found[0].share == 1.0
    tests = [Change("M", "src/a.py"), Change("M", "tests/test_a.py"), Change("M", "docs/a.md")]
    assert find(line(6, changes=tests)).couplings == []


def test_one_person_areas_are_only_reported_when_several_people_commit() -> None:
    many = [Change("M", f"core/src/{i}.py") for i in range(5)]
    solo = line(6, changes=many)
    assert find(solo).one_person_areas == []
    solo[0].author = "Grace"
    solo[0].changes = [Change("M", "docs/a.md")]
    [area] = find(solo).one_person_areas
    assert (area.path, area.touches, area.share) == ("core/src/", 25, 1.0)


def test_ai_marks_come_from_trailers_and_bot_authors() -> None:
    by_trailer = commit("a", [], body="text\n\nCo-Authored-By: Claude <noreply@anthropic.com>")
    by_bot = commit("b", [], author="copilot-swe-agent[bot]")
    plain = commit("c", [], subject="asked Claude about this", body="claude helped")
    assert marks.tools_in(by_trailer) == ["Claude"]
    assert marks.tools_in(by_bot) == ["GitHub Copilot"]
    assert marks.tools_in(plain) == []


# ---- writing --------------------------------------------------------------------------------


def one_chapter(**kwargs: object) -> chapters.ChapterFacts:
    base: dict[str, object] = {
        "index": 1,
        "first_row": 0,
        "last_row": 9,
        "start": START,
        "end": START + timedelta(days=9),
        "commits": 10,
        "merges": 1,
        "has_root": False,
        "areas": [("ui/src/", 0.6), ("api/", 0.25)],
        "tags": ["v0.2.0"],
        "subjects": [("abc1234", "added the launcher")],
    }
    return chapters.ChapterFacts(**{**base, **kwargs})  # type: ignore[arg-type]


def test_the_template_states_counts_dates_areas_and_the_tag() -> None:
    title, text = write.template(one_chapter())
    assert title == "The road to v0.2.0"
    assert text == (
        "10 commits over 10 days, from 1 Jan 2025 to 10 Jan 2025. Most changes were in "
        "ui/src/ (60%) and api/ (25%). One branch was merged. It ends at tag v0.2.0."
    )
    assert write.template(one_chapter(has_root=True))[0] == "The beginning"
    assert write.template(one_chapter(tags=[]))[0] == "Work on ui/src/"
    same_day = one_chapter(end=START, commits=1, merges=0, areas=[], tags=[])
    assert write.template(same_day) == ("More commits", "1 commit on 1 Jan 2025.")


def draft(title: str, summary: str) -> write.Draft:
    return write.Draft(chapters=[write.DraftChapter(index=1, title=title, summary=summary)])


@pytest.mark.parametrize(
    ("title", "summary", "problem"),
    [
        ("Launcher", "Added 12 files for the launcher.", 'remove the number "12"'),
        ("Launcher", "See {def5678} for the launcher.", "not a commit listed"),
        ("Launcher", "An amazing launcher was added.", "overstates"),
        ("Launcher {x}", "The launcher was added.", "braces are only"),
        ("", "The launcher was added.", "the title must be"),
    ],
)
def test_a_draft_that_breaks_a_rule_is_refused(title: str, summary: str, problem: str) -> None:
    assert any(problem in found for found in write.problems(draft(title, summary), [one_chapter()]))


def test_a_draft_may_name_tags_cite_listed_commits_and_use_names_with_digits() -> None:
    good = draft("The road to v0.2.0", "The launcher {abc1234} moved to OAuth2 and utf-8.")
    assert write.problems(good, [one_chapter()]) == []
    assert write.problems(write.Draft(chapters=[]), [one_chapter()]) == ["Chapter 1 is missing."]


async def test_the_model_writes_the_chapters_and_its_citations_become_parts() -> None:
    reply = draft("Building the launcher", "It started with {abc1234}.").model_dump_json()
    [(title, parts, who)] = await write.write(
        [one_chapter()], {"abc1234": "abc1234" + "0" * 33}, MockLLM([reply]), lambda _m: None
    )
    assert (title, who) == ("Building the launcher", "model")
    assert [(p.text, p.commit) for p in parts] == [
        ("It started with ", None),
        ("abc1234", "abc1234" + "0" * 33),
        (".", None),
    ]


async def test_two_bad_drafts_or_a_failing_model_fall_back_to_the_template() -> None:
    warnings: list[str] = []
    bad = draft("Launcher", "Added 12 files.").model_dump_json()
    [(title, _, who)] = await write.write([one_chapter()], {}, MockLLM([bad, bad]), warnings.append)
    assert (title, who) == ("The road to v0.2.0", "template")
    assert "broke the writing rules" in warnings[0]
    [(_, _, who)] = await write.write(
        [one_chapter()], {}, MockLLM([RuntimeError("down")]), warnings.append
    )
    assert who == "template" and "could not write" in warnings[1]


# ---- the agent, on a real repository --------------------------------------------------------


def git(repo: Path, *args: str, day: int = 1, author: str = "Ada") -> None:
    date = f"2025-01-{day:02d}T12:00:00+00:00"
    env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date, "GIT_TERMINAL_PROMPT": "0"}
    subprocess.run(
        ["git", "-c", f"user.name={author}", "-c", "user.email=t@example.com",
         "-c", "commit.gpgsign=false", "-c", "core.autocrlf=false", *args],
        cwd=repo, capture_output=True, text=True, check=True, env={**os.environ, **env},
    )  # fmt: skip


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "demo repo"
    (root / "src").mkdir(parents=True)
    git(root, "init", "-q", "-b", "main")
    (root / "src" / "app.py").write_text("print('one')\n", encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "added the app", day=1)
    git(root, "tag", "v0.1.0")
    for day in range(2, 7):
        (root / "src" / "app.py").write_text(f"print('{day}')\n" * day, encoding="utf-8")
        git(root, "commit", "-qam", f"changed the app, day {day}", day=day)
    git(root, "checkout", "-q", "-b", "feature")
    git(root, "mv", "src/app.py", "src/main.py")
    git(root, "commit", "-q", "-m", "renamed the app", day=7)
    git(root, "checkout", "-q", "main")
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    git(root, "add", "-A")
    git(
        root, "commit", "-q", "-m", "added a readme",
        "-m", "Co-Authored-By: Claude <noreply@anthropic.com>", day=8,
    )  # fmt: skip
    git(root, "merge", "-q", "--no-ff", "feature", "-m", "merged the rename", day=9)
    return root


async def test_the_agent_draws_a_real_history(repo: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = await CommitGraphAgent().execute({"target": str(repo), "output_dir": str(out)})
    assert result.status == "ok", result.error
    data = result.data
    assert data["repo"]["name"] == "demo repo"
    assert (data["repo"]["shown"], data["repo"]["truncated"]) == (9, False)
    assert data["repo"]["lanes"] == 2 and data["repo"]["renames_followed"] == "similar"

    commits = data["commits"]
    assert [c["subject"] for c in commits][0] == "merged the rename"
    assert len(commits[0]["parents"]) == 2 and len(commits[0]["edges"]) == 2
    assert commits[-1]["tags"] == ["v0.1.0"]
    assert [n["kind"] for n in commits[-1]["notes"]] == ["root"]
    assert [n["text"] for n in commits[0]["notes"]] == [
        "Merged a branch of 1 commit, 2 days after it started"
    ]
    assert {c["lane"] for c in commits} == {0, 1}
    assert all(c["chapter"] >= 1 for c in commits)

    app = next(f for f in data["files"] if f["path"] == "src/main.py")
    assert app["alive"] and app["touches"] == 7
    assert app["events"][0] == {"row": 1, "kind": "renamed", "was": "src/app.py"} or any(
        e["kind"] == "renamed" and e["was"] == "src/app.py" for e in app["events"]
    )
    [spot] = data["hotspots"]
    assert spot["path"] == "src/main.py" and spot["lines"] == 6

    [mark] = data["ai_marks"]
    assert (mark["tool"], mark["commits"]) == ("Claude", 1)
    assert "ai" in [n["kind"] for c in commits for n in c["notes"]]

    assert data["chapters"][0]["written_by"] == "template"
    assert result.summary.startswith("9 commits, from 1 Jan 2025 to 9 Jan 2025, in ")
    assert {f.title for f in result.findings} == {"Files that change the most", "AI tool marks"}

    assert data["poster"] == "demo-repo.history.svg"
    svg = (out / "demo-repo.history.svg").read_text(encoding="utf-8")
    assert svg.startswith("<svg ") and "demo repo" in svg and "v0.1.0" in svg
    json.dumps(data)


async def test_max_commits_cuts_the_history_and_says_so(repo: Path) -> None:
    result = await CommitGraphAgent().execute({"target": str(repo), "max_commits": 5})
    assert result.status == "ok", result.error
    assert (result.data["repo"]["shown"], result.data["repo"]["truncated"]) == (5, True)
    assert result.summary.startswith("The newest 5 of 9 commits, from ")
    # the oldest commit drawn still points at a parent that is not drawn
    drawn = {c["hash"] for c in result.data["commits"]}
    assert any(e["to"] not in drawn for c in result.data["commits"] for e in c["edges"])


async def test_paths_limit_the_history_to_a_folder(repo: Path) -> None:
    result = await CommitGraphAgent().execute({"target": str(repo), "paths": ["src"]})
    assert result.status == "ok", result.error
    # the readme commit and the merge are outside src
    assert result.data["repo"]["shown"] == 7
    drawn = {c["hash"] for c in result.data["commits"]}
    assert all(e["to"] in drawn for c in result.data["commits"] for e in c["edges"])


async def test_a_folder_that_is_not_a_repository_is_an_error(tmp_path: Path) -> None:
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain" / "a.txt").write_text("x", encoding="utf-8")
    result = await CommitGraphAgent().execute({"target": str(tmp_path / "plain")})
    assert result.status == "error" and "not a git repository" in (result.error or "")


def test_poster_names_are_safe_and_text_is_escaped() -> None:
    assert poster.safe_stem("../../etc/passwd") == "etc-passwd"
    assert poster.safe_stem("nul") == "_nul"
    assert poster.safe_stem("///") == "history"


def test_listing_the_agent_does_not_need_git() -> None:
    schema = CommitGraphAgent.InputModel.model_json_schema()
    assert schema["properties"]["output_dir"]["format"] == "output-dir"
    assert schema["properties"]["max_commits"]["maximum"] == 3000
