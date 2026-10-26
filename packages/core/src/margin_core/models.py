"""Standard Pydantic models shared by every agent.

A generic UI can render ``summary``, ``findings`` and ``evidence`` of any
:class:`AgentResult` without knowing anything about the agent that produced it.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ResultStatus = Literal["ok", "partial", "error"]
QuestionKind = Literal["choice", "multi_choice", "text"]
AnswerSource = Literal["user", "preset", "default"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(_StrictModel):
    """A single, checkable piece of evidence supporting a finding."""

    kind: str = Field(description='Evidence type, e.g. "file", "commit", "config", "metric".')
    location: str | None = Field(
        default=None, description='Where to look, e.g. "src/utils.py:10-42" or a commit SHA.'
    )
    detail: str = Field(description="Human-readable explanation.")
    weight: float | None = Field(
        default=None, description="Contribution to the score, if applicable."
    )


class Finding(_StrictModel):
    """A titled conclusion backed by evidence."""

    title: str
    severity_or_score: float | None = None
    summary: str
    evidence: list[Evidence] = Field(default_factory=list)


class TokenUsage(_StrictModel):
    """Aggregated LLM usage and estimated cost."""

    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            llm_calls=self.llm_calls + other.llm_calls,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=self.cost_usd + other.cost_usd,
        )

    def __sub__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            llm_calls=self.llm_calls - other.llm_calls,
            input_tokens=self.input_tokens - other.input_tokens,
            output_tokens=self.output_tokens - other.output_tokens,
            cost_usd=max(0.0, self.cost_usd - other.cost_usd),
        )


class Choice(_StrictModel):
    """One option of a :class:`Question`."""

    value: str | int | float | bool = Field(description="What the agent gets when this is picked.")
    label: str = Field(description="What the person sees.")
    detail: str | None = Field(default=None, description="A short explanation of the option.")


def _same(a: Any, b: Any) -> bool:
    # True == 1 in Python, but an answer of 1 must not pick a choice whose value is True
    return bool(a == b) and isinstance(a, bool) == isinstance(b, bool)


class Question(_StrictModel):
    """Something an agent asks the person running it, with the evidence behind the question.

    ``choice`` takes one of ``choices`` (or any text, with ``allow_other``), ``multi_choice``
    takes a list of them, and ``text`` takes free text.
    """

    id: str = Field(
        min_length=1, max_length=200, description='Stable key, e.g. "date_format:order_date".'
    )
    prompt: str = Field(min_length=1, description="The question, as one sentence.")
    detail: str | None = Field(default=None, description="Why the agent is asking.")
    kind: QuestionKind = "choice"
    choices: list[Choice] = Field(default_factory=list)
    allow_other: bool = Field(
        default=False, description="choice only: any text is accepted besides the choices."
    )
    default: Any = Field(
        default=None, description="Used when the question is not asked; the suggested answer."
    )
    required: bool = Field(default=True, description="Whether an empty answer is refused.")
    section: str | None = Field(default=None, description="A heading to group questions under.")
    evidence: list[Evidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def _consistent(self) -> Question:
        if self.kind == "text":
            if self.choices or self.allow_other:
                raise ValueError("a text question takes no choices")
        else:
            if not self.choices:
                raise ValueError(f"a {self.kind} question needs at least one choice")
            values = [c.value for c in self.choices]
            if any(_same(v, w) for i, v in enumerate(values) for w in values[i + 1 :]):
                raise ValueError("choice values must be unique")
            if self.kind == "multi_choice" and self.allow_other:
                raise ValueError("allow_other only applies to choice questions")
        if self.default is not None:
            self.default = self.check(self.default)
        return self

    def _choice(self, value: Any) -> Choice | None:
        return next((c for c in self.choices if _same(c.value, value)), None)

    def check(self, value: Any) -> Any:
        """Return ``value`` in its normal form, or raise ``ValueError`` if it is not accepted."""
        if self.kind == "multi_choice":
            if value is None:
                value = []
            if not isinstance(value, list | tuple):
                raise ValueError("expected a list of choices")
            unknown = [v for v in value if self._choice(v) is None]
            if unknown:
                raise ValueError(f"not among the choices: {', '.join(map(repr, unknown))}")
            if not value and self.required:
                raise ValueError("pick at least one")
            return [c.value for c in self.choices if any(_same(c.value, v) for v in value)]

        if value is None or (isinstance(value, str) and not value.strip()):
            if self.required:
                raise ValueError("an answer is required")
            return None
        if self.kind == "text":
            if not isinstance(value, str):
                raise ValueError("expected text")
            return value.strip()
        choice = self._choice(value)
        if choice is not None:
            return choice.value
        if self.allow_other and isinstance(value, str):
            return value.strip()
        raise ValueError(f"{value!r} is not one of the choices")

    def describe(self, value: Any) -> str:
        """A readable form of an answer to this question."""
        if value is None or value == []:
            return "(no answer)"
        if self.kind == "text":
            return str(value)
        values = value if isinstance(value, list) else [value]
        labels = []
        for v in values:
            choice = self._choice(v)
            labels.append(choice.label if choice is not None else str(v))
        return ", ".join(labels)


class Answer(_StrictModel):
    """How one question was answered, kept with the result so every choice can be traced.

    ``source`` says who decided: ``user`` (answered when asked), ``preset`` (given with the
    run's input) or ``default`` (the question's default was assumed; nobody confirmed it).
    """

    question_id: str
    prompt: str
    value: Any = None
    label: str = Field(description="The answer in readable form.")
    source: AnswerSource

    @classmethod
    def of(cls, question: Question, value: Any, source: AnswerSource) -> Answer:
        return cls(
            question_id=question.id,
            prompt=question.prompt,
            value=value,
            label=question.describe(value),
            source=source,
        )


class QuestionBatch(_StrictModel):
    """Questions asked together, at one point of a run."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    title: str = Field(min_length=1, description='What is being decided, e.g. "Check the plan".')
    detail: str | None = None
    questions: list[Question] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> QuestionBatch:
        ids = [q.id for q in self.questions]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"question ids must be unique: {', '.join(duplicates)}")
        return self

    def resolve(self, raw: Mapping[str, Any], source: AnswerSource) -> dict[str, Answer]:
        """Turn raw answers into :class:`Answer` objects, in question order.

        A question left out takes its default (recorded as ``default``). Raises
        ``ValueError`` listing every problem: unknown ids, missing or invalid answers.
        """
        known = {q.id for q in self.questions}
        problems = [f"{key}: no such question" for key in raw if key not in known]
        answers: dict[str, Answer] = {}
        for question in self.questions:
            if question.id in raw:
                try:
                    value = question.check(raw[question.id])
                except ValueError as exc:
                    problems.append(f"{question.id}: {exc}")
                    continue
                answers[question.id] = Answer.of(question, value, source)
            elif question.default is not None or not question.required:
                default = question.check(question.default)
                answers[question.id] = Answer.of(question, default, "default")
            else:
                problems.append(f"{question.id}: an answer is required")
        if problems:
            raise ValueError("; ".join(problems))
        return answers


class RunMetadata(_StrictModel):
    """Execution metadata attached to every result."""

    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_s: float | None = None
    model: str | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
    answers: list[Answer] = Field(
        default_factory=list, description="Questions the agent asked, and how each was answered."
    )
    extra: dict[str, Any] = Field(default_factory=dict)


class AgentInput(_StrictModel):
    """Base class for agent input models. Unknown fields are rejected."""


class AnswersInput(AgentInput):
    """Base class for the input of an agent that asks questions (``RunContext.ask``).

    The two fields have the same names in every such agent, so a run can be repeated with
    the answers of an earlier one, and scripts can answer up front.
    """

    answers: dict[str, Any] = Field(
        default_factory=dict,
        description="Answers to the agent's questions, by question id. These are not asked.",
    )
    assume_defaults: bool = Field(
        default=False,
        description="Ask nothing: every question takes its suggested answer, marked unconfirmed.",
    )


class AgentResult(_StrictModel):
    """The standard result returned by every agent.

    ``status`` semantics:

    - ``ok``: everything requested was done. ``error`` is null.
    - ``partial``: a usable result, but some requested work was skipped (a budget or time cap
      was hit, some files were unreadable, an optional step was unavailable). Each skipped
      part has an entry in ``warnings``. ``data`` is complete in shape but may hold fewer
      items. ``error`` is null.
    - ``error``: no usable result. ``data`` is empty and ``error`` holds the message.
    """

    agent_id: str
    agent_version: str
    status: ResultStatus
    summary: str = Field(description="2-3 sentence human summary.")
    data: dict[str, Any] = Field(
        default_factory=dict, description="Agent-specific payload, validated by its OutputModel."
    )
    findings: list[Finding] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = Field(default=None, description="Error message when status is 'error'.")
    metadata: RunMetadata = Field(default_factory=RunMetadata)


class ProgressEvent(_StrictModel):
    """A progress update emitted during a run (consumed by CLI/UI)."""

    stage: str
    message: str = ""
    fraction: float | None = Field(default=None, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AgentInfo(_StrictModel):
    """Static description of an agent, including its JSON schemas."""

    id: str
    name: str
    description: str
    version: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    primary_input: str | None = Field(
        default=None, description="Input field filled by a positional CLI argument."
    )
    uses_llm: bool = Field(default=False, description="Whether runs normally call a model.")
