"""Questions an agent asks during a run: the models, ``RunContext.ask`` and the report."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest
from margin_core import (
    AgentResult,
    Answer,
    AnswersInput,
    BaseAgent,
    CancellationToken,
    Choice,
    Evidence,
    InputValidationError,
    NoAnswerError,
    Question,
    QuestionBatch,
    RunContext,
)
from margin_core.reporting import to_markdown
from pydantic import BaseModel, ValidationError

FORMAT = Question(
    id="date_format",
    prompt="Which date format does order_date use?",
    choices=[Choice(value="mdy", label="MM/DD/YYYY"), Choice(value="dmy", label="DD/MM/YYYY")],
    default="mdy",
    evidence=[Evidence(kind="sample", location="order_date", detail="01/02/2024, 03/04/2024")],
)
COLUMNS = Question(
    id="columns",
    prompt="Which columns matter?",
    kind="multi_choice",
    choices=[Choice(value=c, label=c.title()) for c in ("revenue", "cost", "units")],
    default=["revenue"],
)
CONTEXT = Question(id="context", prompt="Anything we should know?", kind="text", required=False)


# ---- the models -------------------------------------------------------------------------


def test_questions_must_be_consistent() -> None:
    with pytest.raises(ValidationError, match="at least one choice"):
        Question(id="q", prompt="?")
    with pytest.raises(ValidationError, match="takes no choices"):
        Question(id="q", prompt="?", kind="text", choices=[Choice(value=1, label="one")])
    with pytest.raises(ValidationError, match="unique"):
        Question(
            id="q", prompt="?", choices=[Choice(value=1, label="a"), Choice(value=1, label="b")]
        )
    with pytest.raises(ValidationError, match="not one of the choices"):
        Question(id="q", prompt="?", choices=[Choice(value="a", label="A")], default="b")
    with pytest.raises(ValidationError, match="unique"):
        QuestionBatch(title="t", questions=[FORMAT, FORMAT])


def test_check_normalises_answers() -> None:
    assert FORMAT.check("dmy") == "dmy"
    with pytest.raises(ValueError, match="required"):
        FORMAT.check(None)
    with pytest.raises(ValueError, match="not one of"):
        FORMAT.check("ymd")

    # lists come back in the order of the choices, whatever order they were given in
    assert COLUMNS.check(["units", "revenue"]) == ["revenue", "units"]
    with pytest.raises(ValueError, match="at least one"):
        COLUMNS.check([])
    with pytest.raises(ValueError, match="not among"):
        COLUMNS.check(["profit"])

    assert CONTEXT.check("  a promo in Q3 ") == "a promo in Q3"
    assert CONTEXT.check("") is None  # optional


def test_true_is_not_one() -> None:
    flag = Question(
        id="q", prompt="?", choices=[Choice(value=True, label="Yes"), Choice(value=0, label="Zero")]
    )
    with pytest.raises(ValueError):
        flag.check(1)
    assert flag.check(True) is True and flag.check(0) == 0


def test_other_text_is_accepted_only_when_allowed() -> None:
    grain = Question(
        id="grain", prompt="One row is one what?", allow_other=True,
        choices=[Choice(value="order", label="An order")],
    )  # fmt: skip
    assert grain.check("order line") == "order line"
    assert grain.describe("order") == "An order"
    assert grain.describe("order line") == "order line"


def test_resolve_fills_defaults_and_lists_every_problem() -> None:
    batch = QuestionBatch(title="Check", questions=[FORMAT, COLUMNS, CONTEXT])
    answers = batch.resolve({"date_format": "dmy"}, "user")
    assert [a.source for a in answers.values()] == ["user", "default", "default"]
    assert answers["columns"].label == "Revenue"
    assert answers["context"].value is None and answers["context"].label == "(no answer)"

    # an optional list left out is an empty list, whichever way it was left out
    optional = COLUMNS.model_copy(update={"required": False, "default": None})
    skipped = QuestionBatch(title="Check", questions=[optional]).resolve({}, "user")
    assert skipped["columns"].value == [] and optional.check(None) == []

    strict = QuestionBatch(title="Check", questions=[Question(id="x", prompt="?", kind="text")])
    with pytest.raises(ValueError) as problem:
        strict.resolve({"nope": 1}, "user")
    assert "nope: no such question" in str(problem.value)
    assert "x: an answer is required" in str(problem.value)


# ---- RunContext.ask ---------------------------------------------------------------------


class AskInput(AnswersInput):
    text_question: bool = False


class AskOutput(BaseModel):
    answers: dict[str, Any]


class Asker(BaseAgent):
    id = "asker"
    name = "Asker"
    description = "Asks, then reports what it was told."
    version = "0.0.1"
    InputModel = AskInput
    OutputModel = AskOutput

    async def run(self, input: AskInput, ctx: RunContext) -> AgentResult:
        questions = [FORMAT, COLUMNS, CONTEXT]
        if input.text_question:
            questions.append(Question(id="must", prompt="Required, no default", kind="text"))
        answers = await ctx.ask(
            questions,
            title="Check the data",
            preset=input.answers,
            assume_defaults=input.assume_defaults,
        )
        return self.make_result(
            summary="asked", output=AskOutput(answers={k: a.value for k, a in answers.items()})
        )


class Scripted:
    """A responder that records what it was asked and answers from a script."""

    def __init__(self, reply: Mapping[str, Any], delay: float = 0.0) -> None:
        self.reply = reply
        self.delay = delay
        self.batches: list[QuestionBatch] = []

    async def __call__(self, batch: QuestionBatch) -> Mapping[str, Any]:
        self.batches.append(batch)
        await asyncio.sleep(self.delay)
        return self.reply


async def test_ask_puts_everything_to_the_responder_at_once() -> None:
    responder = Scripted({"date_format": "dmy", "columns": ["cost"], "context": "promo"})
    result = await Asker().execute({}, RunContext(responder=responder))
    assert result.status == "ok"
    assert result.data["answers"] == {"date_format": "dmy", "columns": ["cost"], "context": "promo"}
    (batch,) = responder.batches
    assert batch.title == "Check the data" and len(batch.questions) == 3
    assert [a.source for a in result.metadata.answers] == ["user", "user", "user"]
    assert result.warnings == []


async def test_preset_answers_are_not_asked() -> None:
    responder = Scripted({"columns": ["units"]})
    preset = {"date_format": "dmy", "context": "promo"}
    result = await Asker().execute({"answers": preset}, RunContext(responder=responder))
    assert [q.id for q in responder.batches[0].questions] == ["columns"]
    sources = {a.question_id: a.source for a in result.metadata.answers}
    assert sources == {"date_format": "preset", "columns": "user", "context": "preset"}


async def test_without_anyone_to_ask_defaults_are_assumed_and_flagged() -> None:
    result = await Asker().execute({})
    assert result.status == "ok"
    assert result.data["answers"] == {"date_format": "mdy", "columns": ["revenue"], "context": None}
    assert all(a.source == "default" for a in result.metadata.answers)
    assert result.warnings == [
        "Not confirmed: Which date format does order_date use? Assumed: MM/DD/YYYY.",
        "Not confirmed: Which columns matter? Assumed: Revenue.",
    ]


async def test_assume_defaults_skips_the_responder() -> None:
    responder = Scripted({})
    result = await Asker().execute({"assume_defaults": True}, RunContext(responder=responder))
    assert result.status == "ok" and responder.batches == []


async def test_a_question_nobody_can_answer_fails_the_run() -> None:
    result = await Asker().execute({"text_question": True})
    assert result.status == "error"
    assert "NoAnswerError" in (result.error or "") and "must" in (result.error or "")
    # but it can be answered up front
    ok = await Asker().execute({"text_question": True, "answers": {"must": "yes"}})
    assert ok.status == "ok"


async def test_invalid_answers_are_refused() -> None:
    preset = await Asker().execute({"answers": {"date_format": "ymd"}})
    assert preset.status == "error" and "not valid" in (preset.error or "")

    replied = await Asker().execute({}, RunContext(responder=Scripted({"date_format": "ymd"})))
    assert replied.status == "error" and "Invalid answers" in (replied.error or "")


async def test_cancelling_while_waiting_stops_the_run_promptly() -> None:
    token = CancellationToken()
    responder = Scripted({}, delay=30)
    run = asyncio.ensure_future(
        Asker().execute({}, RunContext(responder=responder, cancel_token=token))
    )
    await asyncio.sleep(0.05)
    token.cancel()
    result = await asyncio.wait_for(run, timeout=2)
    assert result.status == "error" and result.error == "Run was cancelled"


async def test_no_answer_error_is_part_of_the_public_api() -> None:
    async def gives_up(batch: QuestionBatch) -> Mapping[str, Any]:
        raise NoAnswerError("nobody answered in time")

    result = await Asker().execute({}, RunContext(responder=gives_up))
    assert result.status == "error" and "nobody answered in time" in (result.error or "")


def test_invalid_answers_field_is_an_input_error() -> None:
    with pytest.raises(InputValidationError):
        Asker.parse_input({"answers": "not a mapping"})


# ---- reporting --------------------------------------------------------------------------


def test_markdown_lists_answers_and_who_gave_them() -> None:
    result = AgentResult(agent_id="asker", agent_version="1", status="ok", summary="s")
    result.metadata.answers = [
        Answer.of(FORMAT, "dmy", "user"),
        Answer.of(COLUMNS, ["revenue"], "default"),
    ]
    md = to_markdown(result)
    assert "## Answers" in md
    assert "| Which date format does order_date use? | DD/MM/YYYY | you |" in md
    assert "| Which columns matter? | Revenue | default, not confirmed |" in md
