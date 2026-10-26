"""Tests for the workspace scripts: agent scaffolding, the layout check and mirroring."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import check_agents  # noqa: E402
import mirror_agents  # noqa: E402
import new_agent  # noqa: E402

REAL_ROOT = SCRIPTS.parent

ROOT_PYPROJECT = """[project]
name = "fake-workspace"
version = "0.0.0"

[tool.margin]
repository = "https://github.com/owner/margin"
mirror-owner = "owner"

[tool.uv.sources]
margin-core = { workspace = true }

[tool.mypy]
mypy_path = [
    "packages/core/src",
]
"""

ROOT_README = """# Fake

## Agents

| Agent | What it does | State |
|---|---|---|

## Status
"""


@pytest.fixture
def fake_root(tmp_path: Path) -> Path:
    root = tmp_path / "ws"
    (root / "agents").mkdir(parents=True)
    (root / "pyproject.toml").write_text(ROOT_PYPROJECT, encoding="utf-8")
    (root / "README.md").write_text(ROOT_README, encoding="utf-8")
    (root / "LICENSE").write_text((REAL_ROOT / "LICENSE").read_text(encoding="utf-8"), "utf-8")
    return root


def _scaffold(root: Path, agent_id: str = "license-checker") -> Path:
    return new_agent.scaffold(root, agent_id, "License Checker", "Checks licences.")


def test_real_agents_follow_the_standard() -> None:
    assert check_agents.check_all(REAL_ROOT) == {
        "ai_code_detector": [],
        "data_storyteller": [],
        "echo": [],
    }


def test_scaffolded_agent_passes_the_check(fake_root: Path) -> None:
    agent_dir = _scaffold(fake_root)
    assert agent_dir == fake_root / "agents" / "license_checker"
    try:
        assert check_agents.check_agent(agent_dir, fake_root) == []
    finally:
        for name in [m for m in sys.modules if m.startswith("license_checker")]:
            del sys.modules[name]

    pyproject = (fake_root / "pyproject.toml").read_text(encoding="utf-8")
    assert "margin-license-checker = { workspace = true }" in pyproject
    assert '"agents/license_checker/src",' in pyproject
    readme = (fake_root / "README.md").read_text(encoding="utf-8")
    assert "| [License Checker](agents/license_checker/README.md) | Checks licences. |" in readme


def test_scaffolded_agent_runs(fake_root: Path) -> None:
    agent_dir = _scaffold(fake_root, "word-stats")
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    command += ["-o", "asyncio_mode=auto", str(agent_dir / "tests")]
    proc = subprocess.run(
        command,
        cwd=agent_dir,
        env={**os.environ, "PYTHONPATH": str(agent_dir / "src")},
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest.mark.parametrize(
    ("agent_id", "message"),
    [("Bad_Id", "kebab-case"), ("json", "standard-library"), ("x--y", "kebab-case")],
)
def test_scaffold_rejects_bad_ids(fake_root: Path, agent_id: str, message: str) -> None:
    with pytest.raises(new_agent.ScaffoldError, match=message):
        _scaffold(fake_root, agent_id)


def test_scaffold_refuses_existing_folder(fake_root: Path) -> None:
    _scaffold(fake_root)
    with pytest.raises(new_agent.ScaffoldError, match="already exists"):
        _scaffold(fake_root)


def _problems(root: Path, agent_dir: Path) -> list[str]:
    return check_agents.check_agent(agent_dir, root, import_classes=False)


def test_check_catches_broken_agents(fake_root: Path) -> None:
    agent_dir = _scaffold(fake_root)
    readme = agent_dir / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace("## Limits", "## Caveats")
        + "\nSee [the plan](../../PLAN.md).\n",
        encoding="utf-8",
    )
    (agent_dir / "LICENSE").unlink()
    pyproject = agent_dir / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace('version = "0.1.0"', 'version = "0.2.0"')
        + "\n[tool.uv.sources]\nmargin-core = { workspace = true }\n",
        encoding="utf-8",
    )
    problems = "\n".join(_problems(fake_root, agent_dir))
    assert "missing sections: Limits" in problems
    assert "README.md links outside the folder" in problems
    assert "LICENSE is missing" in problems
    assert "no '## [0.2.0]' entry" in problems
    assert "__version__ must be '0.2.0'" in problems
    assert "must not have [tool.uv.sources]" in problems


def test_check_mirror_rules(fake_root: Path) -> None:
    agent_dir = _scaffold(fake_root)
    pyproject = agent_dir / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    pyproject.write_text(
        text.replace("# mirror = ", "mirror = ").replace("<owner>", "someone-else"), "utf-8"
    )
    problems = "\n".join(_problems(fake_root, agent_dir))
    assert "mirror should be 'owner/margin-license-checker'" in problems
    assert "planned agents are not mirrored" in problems


# ---- mirroring --------------------------------------------------------------------------


def _git(repo: Path, *args: str, date: str = "2024-01-01T12:00:00+00:00") -> str:
    env = {"GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date, "GIT_TERMINAL_PROMPT": "0"}

    return subprocess.run(
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com",
         "-c", "commit.gpgsign=false", *args],
        cwd=repo, capture_output=True, text=True, check=True, env={**os.environ, **env},
    ).stdout  # fmt: skip


@pytest.fixture
def mono(tmp_path: Path) -> Path:
    repo = tmp_path / "mono"
    (repo / "agents" / "demo").mkdir(parents=True)
    (repo / "packages").mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "packages" / "core.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "agents" / "demo" / "README.md").write_text("# Demo\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "first")
    (repo / "packages" / "core.py").write_text("x = 2\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "core only", date="2024-01-02T12:00:00+00:00")
    (repo / "agents" / "demo" / "agent.py").write_text("y = 1\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "demo: agent", date="2024-01-03T12:00:00+00:00")
    return repo


def test_split_contains_only_the_agent_history(mono: Path) -> None:
    sha = mirror_agents.split(mono, "agents/demo")
    assert mirror_agents.split(mono, "agents/demo") == sha  # deterministic
    files = _git(mono, "ls-tree", "-r", "--name-only", sha).split()
    assert files == ["README.md", "agent.py"]
    subjects = _git(mono, "log", "--format=%s", sha).splitlines()
    assert subjects == ["demo: agent", "first"]


def test_push_fast_forwards_and_never_force_pushes(mono: Path, tmp_path: Path) -> None:
    bare = tmp_path / "mirror.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    target = mirror_agents.MirrorTarget("demo", "agents/demo", "owner/margin-demo")
    url = bare.as_uri()

    first = mirror_agents.split(mono, "agents/demo", "HEAD~1")
    assert mirror_agents.push(mono, target, first, "tok", url=url) == "pushed"
    latest = mirror_agents.split(mono, "agents/demo")
    assert mirror_agents.push(mono, target, latest, "tok", url=url) == "pushed"
    assert mirror_agents.push(mono, target, latest, "tok", url=url) == "up to date"
    assert mirror_agents.push(mono, target, first, "tok", url=url) == "up to date"  # older run

    # someone edits the mirror directly: the next push must refuse, not overwrite
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", url, str(work))
    (work / "hotfix.txt").write_text("x\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "direct edit")
    _git(work, "push", "-q", "origin", "main")
    (mono / "agents" / "demo" / "more.py").write_text("z = 1\n", encoding="utf-8")
    _git(mono, "add", ".")
    _git(mono, "commit", "-q", "-m", "demo: more")
    with pytest.raises(mirror_agents.MirrorError, match="edited directly"):
        mirror_agents.push(mono, target, mirror_agents.split(mono, "agents/demo"), "t", url=url)


def test_only_working_agents_with_a_mirror_key_are_targets() -> None:
    assert mirror_agents.mirror_targets(REAL_ROOT) == [
        mirror_agents.MirrorTarget(
            "ai-code-detector", "agents/ai_code_detector", "Waddah0-0/margin-ai-code-detector"
        ),
        mirror_agents.MirrorTarget(
            "data-storyteller", "agents/data_storyteller", "Waddah0-0/margin-data-storyteller"
        ),
    ]  # echo is never mirrored
