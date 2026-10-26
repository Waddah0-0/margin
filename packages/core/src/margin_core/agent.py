"""The agent contract every agent implements."""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel, ValidationError

from margin_core.errors import InputValidationError, LLMError, NoAnswerError, RunCancelledError
from margin_core.llm.base import LLMClient
from margin_core.logging import get_logger
from margin_core.models import (
    AgentInfo,
    AgentResult,
    Answer,
    Finding,
    ProgressEvent,
    Question,
    QuestionBatch,
    ResultStatus,
    TokenUsage,
)

if TYPE_CHECKING:
    from margin_core.loaders.base import LoaderLimits, Workspace
    from margin_core.loaders.filters import FilterConfig

ProgressCallback = Callable[[ProgressEvent], None]
Responder = Callable[[QuestionBatch], Awaitable[Mapping[str, Any]]]
"""Puts a batch of questions to a person and returns the raw answers, by question id."""

_CANCEL_POLL_S = 0.2

__all__ = ["BaseAgent", "CancellationToken", "ProgressCallback", "Responder", "RunContext"]


class CancellationToken:
    """Cooperative cancellation flag shared between a caller and a running agent."""

    def __init__(self) -> None:
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled


class RunContext:
    """Per-run services handed to :meth:`BaseAgent.run`.

    During :meth:`BaseAgent.execute`, ``llm`` is a per-run :class:`LLMSession` opened from the
    configured client, limited by ``max_cost_usd``. Anything added with :meth:`warn` ends up in
    the result's ``warnings``, and every answer from :meth:`ask` in its ``metadata.answers``.

    ``responder`` is how :meth:`ask` reaches a person: the CLI asks in the terminal, the API
    pauses the run until answers are posted. Without one, questions take their defaults.
    """

    def __init__(
        self,
        *,
        llm: LLMClient | None = None,
        progress: ProgressCallback | None = None,
        cancel_token: CancellationToken | None = None,
        logger: logging.Logger | None = None,
        max_cost_usd: float | None = None,
        responder: Responder | None = None,
    ) -> None:
        self.llm = llm
        self.progress = progress
        self.cancel_token = cancel_token or CancellationToken()
        self.logger = logger or get_logger("run")
        self.max_cost_usd = max_cost_usd
        self.responder = responder
        self.warnings: list[str] = []
        self.answers: list[Answer] = []

    def warn(self, message: str) -> None:
        """Record a warning for the result (duplicates are ignored)."""
        self.logger.warning(message)
        if message not in self.warnings:
            self.warnings.append(message)

    def report_progress(self, stage: str, message: str = "", fraction: float | None = None) -> None:
        """Emit a progress event to the caller (CLI spinner, API SSE stream, ...)."""
        self.logger.debug("progress stage=%s fraction=%s %s", stage, fraction, message)
        if self.progress is not None:
            self.progress(ProgressEvent(stage=stage, message=message, fraction=fraction))

    async def load_workspace(
        self,
        target: str,
        *,
        paths: Sequence[str] | None = None,
        branch: str | None = None,
        limits: LoaderLimits | None = None,
        filters: FilterConfig | None = None,
    ) -> Workspace:
        """Load ``target`` (GitHub URL or local path), reporting progress and warnings.

        Use the returned workspace with ``async with`` so temporary clones are removed.
        """
        from margin_core.loaders import load_workspace

        self.report_progress("load", f"Loading {target}")
        workspace = await load_workspace(
            target, paths=paths, branch=branch, limits=limits, filters=filters
        )
        for warning in workspace.warnings:
            self.warn(warning)
        return workspace

    def check_cancelled(self) -> None:
        """Raise :class:`RunCancelledError` if the run was cancelled. Call between steps."""
        if self.cancel_token.cancelled:
            raise RunCancelledError("Run was cancelled")

    async def ask(
        self,
        questions: Sequence[Question],
        *,
        title: str,
        detail: str | None = None,
        preset: Mapping[str, Any] | None = None,
        assume_defaults: bool = False,
    ) -> dict[str, Answer]:
        """Ask the person running the agent, wait for the answers, and return them by id.

        All the questions are asked at once. Questions answered in ``preset`` (usually an
        ``answers`` input field) are not asked. The rest go to the responder, unless there is
        none or ``assume_defaults`` is set: then each takes its default, recorded as not
        confirmed and reported as a warning. A required question without a default that
        cannot be asked raises :class:`NoAnswerError`.
        """
        batch = QuestionBatch(title=title, detail=detail, questions=list(questions))
        preset = preset or {}
        answers: dict[str, Answer] = {}
        for question in batch.questions:
            if question.id in preset:
                try:
                    value = question.check(preset[question.id])
                except ValueError as exc:
                    raise InputValidationError(
                        f"The answer given for {question.id!r} is not valid: {exc}"
                    ) from exc
                answers[question.id] = Answer.of(question, value, "preset")

        remaining = [q for q in batch.questions if q.id not in answers]
        if remaining and self.responder is not None and not assume_defaults:
            pending = batch.model_copy(update={"questions": remaining})
            self.check_cancelled()
            raw = await self._wait_for_answers(self.responder(pending))
            try:
                answers.update(pending.resolve(raw, "user"))
            except ValueError as exc:
                raise InputValidationError(f"Invalid answers: {exc}") from exc
        elif remaining:
            unanswerable = [q.id for q in remaining if q.required and q.default is None]
            if unanswerable:
                raise NoAnswerError(
                    "These questions need an answer and there was no one to ask: "
                    f"{', '.join(unanswerable)}. Give the answers with the run's input."
                )
            for question in remaining:
                answer = Answer.of(question, question.check(question.default), "default")
                answers[question.id] = answer
                if question.default is not None:
                    self.warn(f"Not confirmed: {question.prompt} Assumed: {answer.label}.")

        ordered = {q.id: answers[q.id] for q in batch.questions}
        self.answers.extend(ordered.values())
        return ordered

    async def _wait_for_answers(self, pending: Awaitable[Mapping[str, Any]]) -> Mapping[str, Any]:
        """Await the responder, giving up as soon as the run is cancelled."""
        task = asyncio.ensure_future(pending)
        try:
            while True:
                done, _ = await asyncio.wait({task}, timeout=_CANCEL_POLL_S)
                if done:
                    return task.result()
                self.check_cancelled()
        finally:
            if not task.done():
                task.cancel()

    def require_llm(self) -> LLMClient:
        """Return the LLM client or fail with a clear error if none was configured."""
        if self.llm is None:
            raise LLMError("This agent needs an LLM client, but none was configured")
        return self.llm


class BaseAgent(ABC):
    """Base class for all agents.

    Subclasses set the class attributes and implement :meth:`run`. Callers normally use
    :meth:`execute`, which validates input, times the run, records LLM usage, and turns
    unexpected exceptions into an ``error`` result.
    """

    id: ClassVar[str]
    name: ClassVar[str]
    description: ClassVar[str]
    version: ClassVar[str]
    InputModel: ClassVar[type[BaseModel]]
    OutputModel: ClassVar[type[BaseModel]]
    primary_input: ClassVar[str | None] = None
    uses_llm: ClassVar[bool] = False
    """Whether runs normally call a model (the API queues these separately: one GPU)."""
    """Input field filled by the CLI's positional argument (and shown first in forms)."""

    def __init__(self, llm: LLMClient | None = None, config: Mapping[str, Any] | None = None):
        self.llm = llm
        self.config: dict[str, Any] = dict(config or {})

    @classmethod
    def info(cls) -> AgentInfo:
        return AgentInfo(
            id=cls.id,
            name=cls.name,
            description=cls.description,
            version=cls.version,
            input_schema=cls.InputModel.model_json_schema(),
            output_schema=cls.OutputModel.model_json_schema(),
            primary_input=cls.primary_input,
            uses_llm=cls.uses_llm,
        )

    @classmethod
    def parse_input(cls, raw: BaseModel | Mapping[str, Any]) -> BaseModel:
        """Validate ``raw`` against :attr:`InputModel`."""
        if isinstance(raw, cls.InputModel):
            return raw
        data = raw.model_dump() if isinstance(raw, BaseModel) else dict(raw)
        try:
            return cls.InputModel.model_validate(data)
        except ValidationError as exc:
            raise InputValidationError(f"Invalid input for agent {cls.id!r}:\n{exc}") from exc

    @abstractmethod
    async def run(self, input: Any, ctx: RunContext) -> AgentResult:
        """Do the work. ``input`` is an instance of :attr:`InputModel`."""

    def make_result(
        self,
        *,
        summary: str,
        output: BaseModel | None = None,
        findings: Sequence[Finding] = (),
        warnings: Sequence[str] = (),
        status: ResultStatus = "ok",
    ) -> AgentResult:
        """Build an :class:`AgentResult`, validating ``output`` against :attr:`OutputModel`."""
        data: dict[str, Any] = {}
        if output is not None:
            validated = (
                output
                if isinstance(output, self.OutputModel)
                else self.OutputModel.model_validate(output.model_dump())
            )
            data = validated.model_dump(mode="json")
        return AgentResult(
            agent_id=self.id,
            agent_version=self.version,
            status=status,
            summary=summary,
            data=data,
            findings=list(findings),
            warnings=list(warnings),
        )

    def _error_result(self, message: str) -> AgentResult:
        return AgentResult(
            agent_id=self.id,
            agent_version=self.version,
            status="error",
            summary=f"Run failed: {message}",
            error=message,
        )

    async def execute(
        self, raw_input: BaseModel | Mapping[str, Any], ctx: RunContext | None = None
    ) -> AgentResult:
        """Validate input, run the agent, and attach run metadata.

        Raises :class:`InputValidationError` for bad input; any other failure is returned
        as a result with ``status="error"`` so callers always get a structured result.
        """
        parsed = self.parse_input(raw_input)
        ctx = ctx or RunContext()
        caller_llm = ctx.llm
        client = caller_llm if caller_llm is not None else self.llm
        session = client.session(max_cost_usd=ctx.max_cost_usd) if client is not None else None
        ctx.llm = session
        started_at = datetime.now(UTC)
        t0 = time.perf_counter()
        try:
            ctx.check_cancelled()
            result = await self.run(parsed, ctx)
        except RunCancelledError:
            result = self._error_result("Run was cancelled")
        except Exception as exc:
            ctx.logger.exception("Agent %s failed", self.id)
            result = self._error_result(f"{type(exc).__name__}: {exc}")
        finally:
            ctx.llm = caller_llm

        used_model = session.model if session is not None and session.usage.llm_calls else None
        warnings = _merge_unique(result.warnings, ctx.warnings, session.warnings if session else [])
        metadata = result.metadata.model_copy(
            update={
                "started_at": started_at,
                "finished_at": datetime.now(UTC),
                "duration_s": round(time.perf_counter() - t0, 4),
                "model": result.metadata.model or used_model,
                "usage": session.usage if session else TokenUsage(),
                "answers": [*result.metadata.answers, *ctx.answers],
            }
        )
        return result.model_copy(update={"metadata": metadata, "warnings": warnings})


def _merge_unique(*groups: Sequence[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for item in group:
            if item not in merged:
                merged.append(item)
    return merged
