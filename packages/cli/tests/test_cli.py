"""CLI behaviour: commands, input binding, output streams and every exit code."""

from __future__ import annotations

import asyncio
import io
import json
import os
import signal
import subprocess
import sys
from importlib.metadata import EntryPoint
from pathlib import Path

import pytest
from echo_agent import EchoAgent
from margin_cli import main as cli
from margin_cli.execution import ProgressDisplay, TerminalQuestions, execute_cancellable
from margin_core import (
    AgentInput,
    AgentRegistry,
    AgentResult,
    BaseAgent,
    Choice,
    NoAnswerError,
    ProgressEvent,
    Question,
    QuestionBatch,
    RunContext,
)
from margin_core.models import ResultStatus
from margin_core.registry import ENTRY_POINT_GROUP
from pydantic import BaseModel
from rich.console import Console
from typer.testing import CliRunner

runner = CliRunner()


class TargetInput(AgentInput):
    target: str
    mode: str = "ok"


class FileCount(BaseModel):
    files: int


class Lister(BaseAgent):
    """A loader-based agent: counts the files of a local folder."""

    id = "lister"
    name = "Lister"
    description = "Counts files in a folder."
    version = "0.0.1"
    InputModel = TargetInput
    OutputModel = FileCount
    primary_input = "target"

    async def run(self, input: TargetInput, ctx: RunContext) -> AgentResult:
        if input.mode == "crash":
            raise RuntimeError("boom")
        async with await ctx.load_workspace(input.target) as ws:
            status: ResultStatus = "partial" if input.mode == "partial" else "ok"
            warnings = ["some files skipped"] if status == "partial" else []
            return self.make_result(
                summary=f"{len(ws.files)} files",
                output=FileCount(files=len(ws.files)),
                status=status,
                warnings=warnings,
            )


class NoPrimary(BaseAgent):
    id = "no-primary"
    name = "No primary"
    description = "Takes only named fields."
    version = "0.0.1"
    InputModel = TargetInput
    OutputModel = FileCount

    async def run(self, input: TargetInput, ctx: RunContext) -> AgentResult:
        return self.make_result(summary="ok", output=FileCount(files=0))


@pytest.fixture(autouse=True)
def registry(monkeypatch: pytest.MonkeyPatch) -> AgentRegistry:
    broken = EntryPoint(name="broken", value="no_such_module:Agent", group=ENTRY_POINT_GROUP)
    reg = AgentRegistry([broken])
    for agent in (EchoAgent, Lister, NoPrimary):
        reg.register(agent)
    monkeypatch.setattr(cli, "get_registry", lambda: reg)
    return reg


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("y = 2\n", encoding="utf-8")
    return tmp_path


def invoke(*args: str) -> tuple[int, str, str]:
    result = runner.invoke(cli.app, list(args))
    return result.exit_code, result.stdout, result.stderr


# ---- list / info / version ------------------------------------------------------------


def test_version() -> None:
    code, out, _ = invoke("version")
    assert code == 0 and out.startswith("margin-cli v0.1.0 (core v")


def test_list_table_and_load_errors() -> None:
    code, out, err = invoke("list")
    assert code == 0
    assert "echo" in out and "lister" in out and "Counts files" in out
    assert "Could not load broken" in err and "broken" not in out


def test_list_json() -> None:
    code, out, _ = invoke("list", "--json")
    data = json.loads(out)
    assert code == 0
    assert [a["id"] for a in data["agents"]] == ["echo", "lister", "no-primary"]
    assert data["agents"][0]["primary_input"] == "message"
    assert "input_schema" not in data["agents"][0]
    assert "broken" in data["load_errors"]


def test_info_marks_the_positional_field() -> None:
    code, out, _ = invoke("info", "echo")
    assert code == 0
    assert "message (positional)" in out
    assert "margin run echo <message>" in out


def test_info_json_has_schemas() -> None:
    code, out, _ = invoke("info", "lister", "--json")
    info = json.loads(out)
    assert code == 0 and info["primary_input"] == "target"
    assert info["input_schema"]["required"] == ["target"]


@pytest.mark.parametrize("command", [["info", "nope"], ["run", "nope", "x"], ["info", "broken"]])
def test_unknown_or_broken_agent_exits_3(command: list[str]) -> None:
    code, out, err = invoke(*command)
    assert code == 3 and out == "" and "Error:" in err


# ---- run: input -----------------------------------------------------------------------


def test_run_echo_markdown() -> None:
    code, out, err = invoke("run", "echo", "hello", "--set", "repeat=2")
    assert code == 0
    assert out.startswith("# echo report") and "hello hello" in out
    assert "Model" not in out  # no LLM call was made
    assert err == ""


def test_run_json_stdout_is_pure_json() -> None:
    code, out, _ = invoke("run", "echo", "hi", "--format", "json", "--set", "repeat=3")
    result = json.loads(out)
    assert code == 0 and result["data"]["echoed"] == "hi hi hi"


def test_input_file_and_overrides(tmp_path: Path) -> None:
    payload = tmp_path / "in.json"
    payload.write_text(json.dumps({"message": "from-file", "repeat": 2}), encoding="utf-8")
    code, out, _ = invoke("run", "echo", "-i", str(payload), "-s", "repeat=1", "-f", "json")
    assert code == 0 and json.loads(out)["data"]["echoed"] == "from-file"


def test_string_fields_keep_raw_text() -> None:
    code, out, _ = invoke("run", "echo", "--set", "message=123", "-f", "json")
    assert code == 0 and json.loads(out)["data"]["echoed"] == "123"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["run", "echo", "hi", "--set", "repeat=99"], "Invalid input"),
        (["run", "echo", "hi", "--set", "nope=1"], "Invalid input"),
        (["run", "echo"], "Invalid input"),
        (["run", "no-primary", "x"], "positional"),
        (["run", "echo", "hi", "--set", "message=other"], "both"),
        (["run", "echo", "hi", "--set", "repeat"], "key=value"),
    ],
)
def test_bad_input_exits_2(args: list[str], message: str) -> None:
    code, out, err = invoke(*args)
    assert code == 2 and out == "" and message in err


def test_bad_input_file_exits_2(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2]", encoding="utf-8")
    assert invoke("run", "echo", "-i", str(bad))[0] == 2
    bad.write_text("{nope", encoding="utf-8")
    assert invoke("run", "echo", "-i", str(bad))[0] == 2
    assert invoke("run", "echo", "-i", str(tmp_path / "missing.json"))[0] == 2


# ---- run: output and status -----------------------------------------------------------


def test_loader_based_agent(folder: Path) -> None:
    code, out, _ = invoke("run", "lister", str(folder), "-f", "json")
    assert code == 0 and json.loads(out)["data"] == {"files": 2}


def test_out_file_infers_json(folder: Path, tmp_path: Path) -> None:
    report = tmp_path / "reports" / "r.json"
    code, out, err = invoke("run", "lister", str(folder), "--out", str(report))
    assert code == 0 and out == "" and "Report written to" in err
    assert json.loads(report.read_text(encoding="utf-8"))["status"] == "ok"


def test_out_markdown(folder: Path, tmp_path: Path) -> None:
    report = tmp_path / "r.md"
    assert invoke("run", "lister", str(folder), "-o", str(report))[0] == 0
    assert report.read_text(encoding="utf-8").startswith("# lister report")


def test_error_result_exits_1(folder: Path) -> None:
    code, out, err = invoke("run", "lister", str(folder), "--set", "mode=crash")
    assert code == 1
    assert "## Error" in out and "RuntimeError: boom" in err


def test_missing_target_is_an_error_result(tmp_path: Path) -> None:
    code, _, err = invoke("run", "lister", str(tmp_path / "missing"))
    assert code == 1 and "Path does not exist" in err


def test_partial_exits_0_or_4_with_strict(folder: Path) -> None:
    code, _, err = invoke("run", "lister", str(folder), "--set", "mode=partial")
    assert code == 0 and "Warning: some files skipped" in err
    assert invoke("run", "lister", str(folder), "--set", "mode=partial", "--strict")[0] == 4


# ---- run: LLM selection ---------------------------------------------------------------


def test_explicit_provider_with_mock_llm() -> None:
    code, out, _ = invoke(
        "run", "echo", "ping", "-s", "use_llm=true", "--provider", "mock", "-f", "json"
    )
    result = json.loads(out)
    assert code == 0
    assert result["data"]["llm_reply"] == "ping"
    assert result["metadata"]["usage"]["llm_calls"] == 1


def test_explicit_provider_that_cannot_start_exits_2() -> None:
    code, _, err = invoke("run", "echo", "hi", "--provider", "anthropic")
    assert code == 2 and "ANTHROPIC_API_KEY" in err


def test_unusable_default_provider_does_not_block_agents_without_llm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEFAULT_LLM_PROVIDER", "anthropic")  # no API key set
    assert invoke("run", "echo", "hi")[0] == 0
    code, _, err = invoke("run", "echo", "hi", "-s", "use_llm=true")
    assert code == 1 and "needs an LLM client" in err


def test_max_cost_is_the_run_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[float | None] = []
    real = execute_cancellable

    async def capture(agent: BaseAgent, parsed: BaseModel, ctx: RunContext) -> AgentResult | None:
        seen.append(ctx.max_cost_usd)
        return await real(agent, parsed, ctx)

    monkeypatch.setattr(cli, "execute_cancellable", capture)
    assert invoke("run", "echo", "hi", "--max-cost", "0.25")[0] == 0
    assert invoke("run", "echo", "hi")[0] == 0
    assert seen == [0.25, 1.0]  # explicit value, then the MAX_COST_USD default


# ---- cancellation and progress --------------------------------------------------------


class Slow(BaseAgent):
    id = "slow"
    name = "Slow"
    description = "Loops until cancelled."
    version = "0.0.1"
    InputModel = TargetInput
    OutputModel = FileCount

    async def run(self, input: TargetInput, ctx: RunContext) -> AgentResult:
        for _ in range(500):
            if input.mode == "ok":
                ctx.check_cancelled()
            await asyncio.sleep(0.01)
        return self.make_result(summary="done", output=FileCount(files=0))


async def test_cancel_stops_a_cooperative_agent() -> None:
    ctx = RunContext()
    task = asyncio.create_task(execute_cancellable(Slow(), TargetInput(target="x"), ctx))
    await asyncio.sleep(0.05)
    task.cancel()
    result = await task
    assert ctx.cancel_token.cancelled
    assert result is not None and result.error == "Run was cancelled"


async def test_cancel_gives_up_on_an_agent_that_ignores_it() -> None:
    ctx = RunContext()
    stubborn = TargetInput(target="x", mode="ignore")
    task = asyncio.create_task(execute_cancellable(Slow(), stubborn, ctx, grace_s=0.05))
    await asyncio.sleep(0.05)
    task.cancel()
    assert await task is None


def test_progress_display_text() -> None:
    console = Console(file=io.StringIO(), force_terminal=True)
    display = ProgressDisplay(console, "Lister", enabled=True)
    with display as callback:
        assert callback is not None
        callback(ProgressEvent(stage="scan", message="a.py", fraction=0.5))
        assert display._status is not None
    assert display._status is None


def test_progress_display_off_when_not_a_terminal() -> None:
    console = Console(file=io.StringIO(), force_terminal=False)
    with ProgressDisplay(console, "Lister", enabled=True) as callback:
        assert callback is None


# ---- run: questions ---------------------------------------------------------------------


def test_without_a_terminal_questions_take_their_defaults() -> None:
    code, out, err = invoke("run", "echo", "hi", "--set", "ask=true")
    assert code == 0 and "hi" in out
    assert "| How should the message be echoed? | As typed | default, not confirmed |" in out
    assert "Not confirmed: How should the message be echoed? Assumed: As typed." in err


def test_answers_can_be_given_up_front() -> None:
    answers = 'answers={"style": "capitals"}'
    code, out, err = invoke("run", "echo", "hi", "-s", "ask=true", "-s", answers, "-f", "json")
    result = json.loads(out)
    assert code == 0 and result["data"]["echoed"] == "HI"
    assert result["metadata"]["answers"][0]["source"] == "preset"
    assert err == ""


QUESTIONS = QuestionBatch(
    title="Check the data",
    questions=[
        Question(
            id="format", prompt="Date format?", default="mdy",
            choices=[Choice(value="mdy", label="MM/DD"), Choice(value="dmy", label="DD/MM")],
        ),
        Question(
            id="columns", prompt="Columns?", kind="multi_choice", section="Columns",
            choices=[Choice(value=c, label=c) for c in ("revenue", "cost", "units")],
        ),
        Question(id="grain", prompt="One row is?", allow_other=True,
                 choices=[Choice(value="order", label="An order")]),
        Question(id="note", prompt="Anything else?", kind="text", required=False),
    ],
)  # fmt: skip


def ask_in_terminal(typed: str) -> tuple[dict[str, object], str]:
    console = Console(file=io.StringIO(), force_terminal=False, width=200)
    asker = TerminalQuestions(console, stream=io.StringIO(typed))
    answers = asyncio.run(asker(QUESTIONS))
    return answers, console.file.getvalue()  # type: ignore[attr-defined]


def test_terminal_questions_accept_numbers_labels_and_defaults() -> None:
    answers, shown = ask_in_terminal("\n3,revenue\norder line\n\n")
    assert answers == {
        "format": "mdy",  # Enter took the suggestion
        "columns": ["revenue", "units"],
        "grain": "order line",  # typed text, allowed by allow_other
        "note": None,
    }
    assert "Check the data" in shown and "Columns" in shown
    assert "1) MM/DD (suggested)" in shown
    assert "Choose 1-2 [1]:" in shown and "(optional):" in shown


def test_terminal_questions_ask_again_after_a_bad_answer() -> None:
    answers, shown = ask_in_terminal("7\n2\n\n1\n1\nnote\n")
    assert answers["format"] == "dmy" and answers["columns"] == ["revenue"]
    assert "Type a number from 1 to 2" in shown
    assert "pick at least one" in shown  # an empty answer to a required list


def test_terminal_questions_stop_when_input_ends() -> None:
    with pytest.raises(NoAnswerError, match="input ended"):
        ask_in_terminal("1\n")


SIGINT_SCRIPT = """
import asyncio, sys
from margin_cli import main as cli
from margin_core import AgentInput, AgentRegistry, AgentResult, BaseAgent, RunContext
from pydantic import BaseModel

class In(AgentInput):
    target: str

class Out(BaseModel):
    n: int

class Slow(BaseAgent):
    id = "slow"; name = "Slow"; description = "slow"; version = "0.0.1"
    InputModel = In; OutputModel = Out; primary_input = "target"
    async def run(self, input, ctx):
        print("started", file=sys.stderr, flush=True)
        for _ in range(3000):
            ctx.check_cancelled()
            await asyncio.sleep(0.01)
        return self.make_result(summary="done", output=Out(n=1))

registry = AgentRegistry([])
registry.register(Slow)
cli.get_registry = lambda: registry
cli.app(["run", "slow", "x", "--quiet"])
"""


@pytest.mark.skipif(sys.platform == "win32", reason="SIGINT cannot be sent to a child on Windows")
def test_ctrl_c_cancels_and_exits_130() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", SIGINT_SCRIPT],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "MARGIN_ENV_FILE": ""},
    )
    assert proc.stderr is not None
    assert proc.stderr.readline().strip() == "started"
    proc.send_signal(signal.SIGINT)
    out, err = proc.communicate(timeout=30)
    assert proc.returncode == 130, err
    assert out == "" and "Cancelled" in err
