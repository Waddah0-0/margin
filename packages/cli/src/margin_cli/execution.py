"""Running an agent from the CLI: LLM setup, progress, questions and Ctrl+C handling."""

from __future__ import annotations

import asyncio
import contextlib
import sys
import threading
from collections.abc import Callable, Iterator
from typing import IO, Any

from margin_core import (
    AgentResult,
    BaseAgent,
    NoAnswerError,
    ProgressEvent,
    Question,
    QuestionBatch,
    RunContext,
)
from margin_core.config import Settings
from margin_core.errors import LLMError
from margin_core.llm import LLMClient, create_llm
from pydantic import BaseModel
from rich.console import Console
from rich.markup import escape

CANCEL_GRACE_S = 5.0
"""How long a cancelled agent gets to stop on its own before its task is cancelled."""


class ExplicitLLMError(Exception):
    """The user asked for a specific provider or model, and it cannot be set up."""


def make_llm(
    provider: str | None, model: str | None, max_cost_usd: float, settings: Settings
) -> LLMClient | None:
    """Create the LLM client for a run.

    Creating a client never contacts the server, so the default (local) client is always
    created and only used if the agent asks for it. If the default provider cannot be set
    up (e.g. a hosted provider without an API key), the run continues without an LLM and
    agents that need one fail with a clear error. If the user chose ``--provider`` or
    ``--model`` explicitly, any problem is reported straight away.
    """
    try:
        return create_llm(provider, model, max_cost_usd=max_cost_usd, settings=settings)
    except LLMError as exc:
        if provider is not None or model is not None:
            raise ExplicitLLMError(str(exc)) from exc
        return None


async def execute_cancellable(
    agent: BaseAgent,
    parsed_input: BaseModel,
    ctx: RunContext,
    *,
    grace_s: float = CANCEL_GRACE_S,
) -> AgentResult | None:
    """Run the agent; if this task is cancelled (Ctrl+C), cancel cooperatively.

    The agent gets ``grace_s`` seconds to notice the cancellation token and return its own
    result. After that its task is cancelled and ``None`` is returned.
    """
    task = asyncio.ensure_future(agent.execute(parsed_input, ctx))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None:
            current.uncancel()  # we handle the cancellation ourselves
        ctx.cancel_token.cancel()
        try:
            return await asyncio.wait_for(asyncio.shield(task), timeout=grace_s)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
            return None


class ProgressDisplay:
    """A one-line spinner on stderr, driven by the agent's progress events."""

    def __init__(self, console: Console, agent_name: str, enabled: bool) -> None:
        self._console = console
        self._agent_name = agent_name
        self._enabled = enabled and console.is_terminal
        self._status: Any = None

    def __enter__(self) -> Callable[[ProgressEvent], None] | None:
        if not self._enabled:
            return None
        self._status = self._console.status(f"{self._agent_name}: starting")
        self._status.__enter__()
        return self.update

    def update(self, event: ProgressEvent) -> None:
        text = f"{self._agent_name}: {event.stage}"
        if event.message:
            text += f" - {event.message}"
        if event.fraction is not None:
            text += f" ({event.fraction:.0%})"
        if self._status is not None:
            self._status.update(text)

    def __exit__(self, *exc: object) -> None:
        if self._status is not None:
            self._status.__exit__(None, None, None)
            self._status = None

    @contextlib.contextmanager
    def paused(self) -> Iterator[None]:
        """Hide the spinner while something else uses the terminal."""
        status = self._status
        if status is not None:
            status.stop()
        try:
            yield
        finally:
            if status is not None and self._status is status:
                status.start()


class TerminalQuestions:
    """Answers an agent's questions by asking in the terminal.

    Prompts go to stderr, so stdout is still only the report. Lines are read on a daemon
    thread, so Ctrl+C cancels the run even while a prompt is waiting.
    """

    def __init__(
        self,
        console: Console,
        display: ProgressDisplay | None = None,
        stream: IO[str] | None = None,
    ) -> None:
        self._console = console
        self._display = display
        self._stream = stream

    async def __call__(self, batch: QuestionBatch) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()

        def settle(answers: dict[str, Any] | None, error: BaseException | None) -> None:
            if future.done():
                return
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(answers or {})

        def work() -> None:
            answers: dict[str, Any] | None = None
            error: BaseException | None = None
            try:
                answers = self.ask_batch(batch)
            except BaseException as exc:  # noqa: BLE001 - handed to the run
                error = exc
            with contextlib.suppress(RuntimeError):  # the run ended and its loop is gone
                loop.call_soon_threadsafe(settle, answers, error)

        paused = self._display.paused() if self._display else contextlib.nullcontext()
        with paused:
            threading.Thread(target=work, name="margin-questions", daemon=True).start()
            return await future

    def ask_batch(self, batch: QuestionBatch) -> dict[str, Any]:
        """Ask every question in turn (blocking). Raises :class:`NoAnswerError` at end of input."""
        out = self._console
        out.print()
        out.print(f"[bold]{escape(batch.title)}[/]", highlight=False)
        if batch.detail:
            out.print(escape(batch.detail), highlight=False)
        answers: dict[str, Any] = {}
        section: str | None = None
        for question in batch.questions:
            if question.section and question.section != section:
                section = question.section
                out.print(f"\n[bold underline]{escape(section)}[/]", highlight=False)
            try:
                answers[question.id] = self._ask(question)
            except EOFError:
                raise NoAnswerError("The input ended before the questions were answered.") from None
        out.print()
        return answers

    def _ask(self, question: Question) -> Any:
        out = self._console
        out.print(f"\n[bold]{escape(question.prompt)}[/]", highlight=False)
        if question.detail:
            out.print(f"  [dim]{escape(question.detail)}[/]", highlight=False)
        for ev in question.evidence:
            where = f"{ev.location}: " if ev.location else ""
            out.print(
                f"  [dim]· {escape(ev.kind)}: {escape(where + ev.detail)}[/]", highlight=False
            )
        suggested = question.default if isinstance(question.default, list) else [question.default]
        for n, choice in enumerate(question.choices, 1):
            line = f"  {n}) {escape(choice.label)}"
            if choice.detail:
                line += f" [dim]- {escape(choice.detail)}[/]"
            if any(choice.value == s and type(choice.value) is type(s) for s in suggested):
                line += " [cyan](suggested)[/]"
            out.print(line, highlight=False)

        while True:
            raw = self._read(self._prompt(question)).strip()
            try:
                value = question.default if not raw else _parse(question, raw)
                return question.check(value)
            except ValueError as exc:
                out.print(f"  [red]{escape(str(exc))}[/]", highlight=False)

    def _prompt(self, question: Question) -> str:
        if question.kind == "text":
            hint = "Your answer"
        elif question.kind == "multi_choice":
            hint = "Numbers, separated by commas" + ("" if question.required else ", or none")
        else:
            hint = f"Choose 1-{len(question.choices)}"
            if question.allow_other:
                hint += ", or type your own"
        if question.default not in (None, []):
            default = question.default if isinstance(question.default, list) else [question.default]
            numbers = [
                str(n)
                for n, c in enumerate(question.choices, 1)
                if any(c.value == d and type(c.value) is type(d) for d in default)
            ]
            shown = ",".join(numbers) if question.choices and numbers else str(question.default)
            hint += f" [{shown}]"
        elif not question.required:
            hint += " (optional)"
        return f"[cyan]{escape(hint)}:[/] "

    def _read(self, prompt: str) -> str:
        self._console.print(prompt, end="", highlight=False)
        line = (self._stream or sys.stdin).readline()
        if not line:
            raise EOFError
        return line.rstrip("\r\n")


def _parse(question: Question, raw: str) -> Any:
    """Turn what was typed into a value for ``question.check``."""
    if question.kind == "text":
        return raw
    if question.kind == "multi_choice":
        if raw.lower() in {"none", "-"}:
            return []
        return [_pick(question, part.strip()) for part in raw.split(",") if part.strip()]
    try:
        return _pick(question, raw)
    except ValueError:
        if question.allow_other:
            return raw
        raise


def _pick(question: Question, typed: str) -> Any:
    """The value of the choice ``typed`` names: by number, label or value."""
    if typed.isdigit() and 1 <= int(typed) <= len(question.choices):
        return question.choices[int(typed) - 1].value
    for choice in question.choices:
        if typed.casefold() in {choice.label.casefold(), str(choice.value).casefold()}:
            return choice.value
    raise ValueError(f"Type a number from 1 to {len(question.choices)}")
