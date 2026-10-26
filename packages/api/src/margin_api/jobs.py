"""Background runs: an in-memory store, two concurrency pools, events and cancellation.

A run moves through ``queued -> running -> done`` (or ``cancelled``). A run whose agent
fails still ends as ``done``: the failure is in its result (``status="error"``), not in the
run's state. Progress events are numbered and kept in a bounded buffer, so a client that
connects late (or reconnects) gets everything it missed.

When the agent asks a question, the run goes ``running -> waiting`` and gives its place in
the pool to the next run, so a question nobody answers never holds the GPU. Once answered
it goes back to ``queued`` and runs again when a place is free.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from margin_core import (
    AgentRegistry,
    AgentResult,
    BaseAgent,
    NoAnswerError,
    ProgressEvent,
    QuestionBatch,
    RunContext,
)
from margin_core.llm import LLMClient
from margin_core.logging import get_logger
from pydantic import BaseModel

from margin_api.settings import ApiSettings

RunStatus = Literal["queued", "running", "waiting", "done", "cancelled"]
EventKind = Literal["status", "progress", "question", "result"]
FINISHED: frozenset[str] = frozenset({"done", "cancelled"})
logger = get_logger("api.jobs")


class NotWaitingError(Exception):
    """Answers were posted to a run that is not waiting for them."""


@dataclass
class RunEvent:
    seq: int
    kind: EventKind
    data: dict[str, Any]


@dataclass
class Run:
    id: str
    agent_id: str
    pool: str
    status: RunStatus = "queued"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    progress: ProgressEvent | None = None
    result: AgentResult | None = None
    events: deque[RunEvent] = field(default_factory=deque)
    token: Any = None  # CancellationToken, set when created
    task: asyncio.Task[None] | None = None
    llm: LLMClient | None = None  # the model client for this run, if the agent uses one
    llm_provider: str | None = None
    llm_model: str | None = None
    finished_monotonic: float | None = None
    question: QuestionBatch | None = None  # what the run is waiting on
    answer: asyncio.Future[Mapping[str, Any]] | None = None
    holds_slot: bool = False  # whether it has a place in its pool right now
    _seq: int = 0
    _changed: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def last_event(self) -> int:
        return self._seq

    def set_status(self, status: RunStatus) -> None:
        self.status = status
        self.add_event("status", {"status": status})

    def add_event(self, kind: EventKind, data: dict[str, Any]) -> None:
        self._seq += 1
        self.events.append(RunEvent(self._seq, kind, data))
        # wake every waiting subscriber, then arm a fresh event for the next change
        self._changed.set()
        self._changed = asyncio.Event()


class _Pool:
    """A FIFO concurrency limit that can report queue positions."""

    def __init__(self, size: int) -> None:
        self.semaphore = asyncio.Semaphore(size)
        self.waiting: deque[str] = deque()

    def position(self, run_id: str) -> int | None:
        try:
            return self.waiting.index(run_id) + 1
        except ValueError:
            return None


class RunManager:
    def __init__(self, registry: AgentRegistry, settings: ApiSettings) -> None:
        self.registry = registry
        self.settings = settings
        self.runs: dict[str, Run] = {}
        self.pools = {
            "llm": _Pool(settings.llm_concurrency),  # runs on the local model (one GPU)
            "other": _Pool(settings.other_concurrency),  # everything else, hosted models too
        }
        self._sweeper: asyncio.Task[None] | None = None

    # ---- lifecycle ------------------------------------------------------------------

    async def start(self) -> None:
        self._sweeper = asyncio.create_task(self._sweep_forever())

    async def stop(self) -> None:
        if self._sweeper is not None:
            self._sweeper.cancel()
        for run in self.runs.values():
            if run.task is not None and not run.task.done():
                run.task.cancel()

    # ---- runs -----------------------------------------------------------------------

    def submit(
        self,
        agent_cls: type[BaseAgent],
        parsed: BaseModel,
        *,
        llm: LLMClient | None = None,
        provider: str | None = None,
    ) -> Run:
        """Queue a run. ``llm`` is this run's model client (created from the current
        settings, so a change in settings applies to the next run); ``provider`` decides the
        queue: only runs on the local model wait for the single local GPU."""
        from margin_core import CancellationToken

        pool = "llm" if agent_cls.uses_llm and provider == "local" else "other"
        run = Run(id=uuid.uuid4().hex, agent_id=agent_cls.id, pool=pool)
        if agent_cls.uses_llm:
            run.llm, run.llm_provider = llm, provider
            run.llm_model = llm.model if llm is not None else None
        run.token = CancellationToken()
        run.events = deque(maxlen=self.settings.event_buffer)
        self.runs[run.id] = run
        self.pools[pool].waiting.append(run.id)
        run.add_event("status", {"status": "queued"})
        run.task = asyncio.create_task(self._execute(run, agent_cls, parsed))
        self._enforce_capacity()
        return run

    def get(self, run_id: str) -> Run | None:
        return self.runs.get(run_id)

    def queue_position(self, run: Run) -> int | None:
        return self.pools[run.pool].position(run.id) if run.status == "queued" else None

    async def _take_slot(self, run: Run) -> None:
        """Wait in line for a place in the run's pool."""
        pool = self.pools[run.pool]
        if run.id not in pool.waiting:
            pool.waiting.append(run.id)
        try:
            await pool.semaphore.acquire()
        finally:
            with contextlib.suppress(ValueError):
                pool.waiting.remove(run.id)
        run.holds_slot = True

    def _free_slot(self, run: Run) -> None:
        if run.holds_slot:
            run.holds_slot = False
            self.pools[run.pool].semaphore.release()

    async def _execute(self, run: Run, agent_cls: type[BaseAgent], parsed: BaseModel) -> None:
        try:
            await self._take_slot(run)
            if run.token.cancelled:
                self._finish(run, None, cancelled=True)
                return
            run.started_at = datetime.now(UTC)
            run.set_status("running")

            def on_progress(event: ProgressEvent) -> None:
                run.progress = event
                run.add_event("progress", event.model_dump(mode="json"))

            async def ask(batch: QuestionBatch) -> Mapping[str, Any]:
                return await self._wait_for_answers(run, batch)

            agent = agent_cls(llm=run.llm)
            ctx = RunContext(progress=on_progress, cancel_token=run.token, responder=ask)
            result = await agent.execute(parsed, ctx)
            self._finish(run, result, cancelled=run.token.cancelled)
        except asyncio.CancelledError:
            self._finish(run, None, cancelled=True)
        except Exception as exc:  # noqa: BLE001 - never lose a run silently
            logger.exception("Run %s crashed outside the agent", run.id)
            self._finish(
                run,
                AgentResult(
                    agent_id=run.agent_id,
                    agent_version="unknown",
                    status="error",
                    summary="The server failed to run this agent.",
                    error=str(exc),
                ),  # fmt: skip
                cancelled=False,
            )
        finally:
            self._free_slot(run)

    # ---- questions ------------------------------------------------------------------

    async def _wait_for_answers(self, run: Run, batch: QuestionBatch) -> Mapping[str, Any]:
        """The run's responder: pause, free the pool place, and wait for answers."""
        run.answer = asyncio.get_running_loop().create_future()
        run.question = batch
        self._free_slot(run)
        run.set_status("waiting")
        run.add_event("question", batch.model_dump(mode="json"))
        try:
            answers = await asyncio.wait_for(run.answer, self.settings.answer_timeout_s)
        except TimeoutError:
            limit = self.settings.answer_timeout_s
            span = f"{round(limit / 60)} minutes" if limit >= 120 else f"{limit:g} seconds"
            raise NoAnswerError(f"No answer came within {span}, so the run stopped.") from None
        finally:
            run.question = None
            run.answer = None
        run.set_status("queued")
        await self._take_slot(run)
        run.set_status("running")
        return answers

    def answer(self, run: Run, batch_id: str, answers: Mapping[str, Any]) -> None:
        """Resume a waiting run. Raises :class:`NotWaitingError`, or ``ValueError`` for
        answers that do not fit the questions (nothing is changed then)."""
        if run.status != "waiting" or run.question is None or run.answer is None:
            raise NotWaitingError("This run is not waiting for answers")
        if batch_id != run.question.id or run.answer.done():
            raise NotWaitingError("These questions have already been answered")
        run.question.resolve(answers, "user")
        run.answer.set_result(dict(answers))

    def _finish(self, run: Run, result: AgentResult | None, *, cancelled: bool) -> None:
        if run.status in FINISHED:
            return
        with contextlib.suppress(ValueError):
            self.pools[run.pool].waiting.remove(run.id)
        run.status = "cancelled" if cancelled else "done"
        run.result = result
        run.finished_at = datetime.now(UTC)
        run.finished_monotonic = time.monotonic()
        run.add_event("status", {"status": run.status})
        run.add_event(
            "result",
            {"status": run.status, "result": result.model_dump(mode="json") if result else None},
        )

    async def cancel(self, run: Run) -> None:
        """Ask the run to stop; force it after the grace period."""
        if run.status in FINISHED:
            return
        run.token.cancel()
        if run.status == "queued":
            if run.task is not None:
                run.task.cancel()
            self._finish(run, None, cancelled=True)
            return
        asyncio.create_task(self._force_after_grace(run))

    async def _force_after_grace(self, run: Run) -> None:
        await asyncio.sleep(self.settings.cancel_grace_s)
        if run.status not in FINISHED and run.task is not None:
            logger.warning("Run %s ignored cancellation; stopping its task", run.id)
            run.task.cancel()

    # ---- events ---------------------------------------------------------------------

    async def events(self, run: Run, after: int = 0) -> AsyncIterator[RunEvent]:
        """Yield events with ``seq > after`` (buffered first), until the result event."""
        while True:
            pending = [e for e in list(run.events) if e.seq > after]
            for event in pending:
                yield event
                after = event.seq
                if event.kind == "result":
                    return
            if run.status in FINISHED and not pending:
                return
            await run._changed.wait()

    # ---- housekeeping -----------------------------------------------------------------

    def _enforce_capacity(self) -> None:
        finished = sorted(
            (r for r in self.runs.values() if r.status in FINISHED),
            key=lambda r: r.finished_monotonic or 0.0,
        )
        while len(self.runs) > self.settings.max_runs and finished:
            self.runs.pop(finished.pop(0).id, None)

    def sweep(self) -> int:
        """Forget finished runs older than the TTL. Returns how many were removed."""
        now = time.monotonic()
        expired = [
            r.id for r in self.runs.values()
            if r.finished_monotonic is not None
            and now - r.finished_monotonic > self.settings.result_ttl_s
        ]  # fmt: skip
        for run_id in expired:
            self.runs.pop(run_id, None)
        return len(expired)

    async def _sweep_forever(self) -> None:
        while True:
            await asyncio.sleep(max(1.0, min(60.0, self.settings.result_ttl_s)))
            self.sweep()
