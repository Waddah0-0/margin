"""The FastAPI application: list agents, start runs, follow them live, cancel them."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable, MutableMapping
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from margin_core import (
    AgentInfo,
    AgentLoadError,
    AgentNotFoundError,
    AgentRegistry,
    AgentResult,
    BaseAgent,
    InputValidationError,
    ProgressEvent,
    QuestionBatch,
    default_registry,
)
from margin_core.config import get_settings
from margin_core.llm import LLMClient, create_llm
from margin_core.logging import get_logger
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from margin_api import __version__
from margin_api.jobs import NotWaitingError, Run, RunManager, RunStatus
from margin_api.llm_settings import router as llm_settings_router
from margin_api.settings import ApiSettings, load_settings

logger = get_logger(__name__)

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


class AgentList(BaseModel):
    agents: list[AgentInfo]
    load_errors: dict[str, str] = Field(
        default_factory=dict, description="Installed agents that failed to load, and why."
    )


class RunCreated(BaseModel):
    run_id: str
    status: RunStatus
    queue_position: int | None
    links: dict[str, str]


class RunModel(BaseModel):
    provider: str
    model: str | None


class RunView(BaseModel):
    run_id: str
    agent_id: str
    status: RunStatus
    queue_position: int | None = Field(description="1 = next to start; null unless queued.")
    progress: ProgressEvent | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    result: AgentResult | None = Field(description="Present once the run is done.")
    llm: RunModel | None = Field(default=None, description="The model this run uses, if any.")
    question: QuestionBatch | None = Field(
        default=None, description="What the run is asking; present only while it is waiting."
    )
    last_event: int = Field(
        default=0, description="Number of the latest event; this view already includes it."
    )


class AnswersBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    batch: str = Field(description="The id of the questions being answered (`question.id`).")
    answers: dict[str, Any] = Field(
        default_factory=dict,
        description="Answers by question id. A question left out takes its default.",
    )


class _BodyLimit:
    """Reject request bodies over ``limit`` bytes with 413, including chunked uploads.

    The body is read here (it is small by definition) and replayed to the app, because an
    error raised while the app reads its body would be reported as a generic 400.
    """

    def __init__(self, app: Any, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method") in {"GET", "HEAD", "DELETE", "OPTIONS"}:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        declared = headers.get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.limit:
            await self._reject(send)
            return
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > self.limit:
                await self._reject(send)
                return
            chunks.append(chunk)
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def _reject(self, send: Send) -> None:
        body = json.dumps({"detail": f"Request body exceeds {self.limit} bytes"}).encode()
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"application/json")]})  # fmt: skip
        await send({"type": "http.response.body", "body": body})


LLMFactory = Callable[[str | None, str | None], LLMClient | None]


def _default_llm(provider: str | None, model: str | None) -> LLMClient | None:
    """A client built from the settings as they are now, so changes apply to the next run."""
    return create_llm(provider, model)


def create_app(
    *,
    registry: AgentRegistry | None = None,
    settings: ApiSettings | None = None,
    llm_factory: LLMFactory | None = _default_llm,
) -> FastAPI:
    settings = settings or load_settings()
    registry = registry or default_registry()
    manager = RunManager(registry, settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await manager.start()
        try:
            yield
        finally:
            await manager.stop()

    app = FastAPI(
        title="margin API",
        version=__version__,
        description=(
            "Run any installed margin agent over HTTP. Runs are asynchronous: start one, "
            "then poll it or follow its events (server-sent events) until the result arrives."
        ),
        lifespan=lifespan,
    )
    app.state.manager = manager
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )
    app.add_middleware(_BodyLimit, limit=settings.max_body_bytes)
    ui_dir = Path(settings.ui_dir) if settings.ui_dir else _bundled_ui()
    ui_root = _ui_root(ui_dir) if ui_dir is not None else None
    if ui_root is not None:
        app.add_middleware(_UIPages, root=ui_root)
    # Only answer requests addressed to this machine by name. Without this, a web page could
    # use DNS rebinding to reach the API through a domain of its own and read local results.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.include_router(llm_settings_router)

    def agent_class(agent_id: str) -> type[BaseAgent]:
        try:
            return registry.get_agent_class(agent_id)
        except AgentNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except AgentLoadError as exc:
            raise HTTPException(500, f"Agent {agent_id!r} failed to load: {exc}") from exc

    def find_run(run_id: str) -> Run:
        run = manager.get(run_id)
        if run is None:
            raise HTTPException(404, f"No run {run_id!r} (unknown, or expired)")
        return run

    def view(run: Run) -> RunView:
        llm = RunModel(provider=run.llm_provider, model=run.llm_model) if run.llm_provider else None
        return RunView(
            run_id=run.id, agent_id=run.agent_id, status=run.status,
            queue_position=manager.queue_position(run), progress=run.progress,
            created_at=run.created_at, started_at=run.started_at,
            finished_at=run.finished_at, result=run.result,
            llm=llm, question=run.question, last_event=run.last_event,
        )  # fmt: skip

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/agents", response_model=AgentList, tags=["agents"])
    def list_agents() -> AgentList:
        return AgentList(agents=registry.list_agents(), load_errors=registry.load_errors)

    @app.get("/agents/{agent_id}", response_model=AgentInfo, tags=["agents"])
    def get_agent(agent_id: str) -> AgentInfo:
        return agent_class(agent_id).info()

    @app.post(
        "/agents/{agent_id}/runs",
        status_code=202,
        response_model=RunCreated,
        tags=["runs"],
        responses={422: {"description": "The input does not match the agent's input schema"}},
    )
    async def start_run(
        agent_id: str,
        body: dict[str, Any],
        provider: Literal["local", "anthropic", "openai", "mock"] | None = Query(
            default=None, description="Model provider for this run (default: from settings)."
        ),
        model: str | None = Query(
            default=None,
            description="Model for this run (default: the provider's model in settings).",
        ),
    ) -> RunCreated:
        cls = agent_class(agent_id)
        try:
            parsed = cls.parse_input(body)
        except InputValidationError as exc:
            raise HTTPException(422, str(exc)) from exc
        llm: LLMClient | None = None
        resolved = (provider or get_settings().default_llm_provider).lower()
        if cls.uses_llm and llm_factory is not None:
            try:
                llm = llm_factory(provider, model)
            except Exception as exc:  # noqa: BLE001 - e.g. a missing API key
                if provider or model:  # a choice made for this run must work, or say why
                    raise HTTPException(422, f"Cannot use that model: {exc}") from exc
                logger.warning("No model client for %s: %s", agent_id, exc)
        run = manager.submit(cls, parsed, llm=llm, provider=resolved)
        return RunCreated(
            run_id=run.id,
            status=run.status,
            queue_position=manager.queue_position(run),
            links={"self": f"/runs/{run.id}", "events": f"/runs/{run.id}/events"},
        )

    @app.get("/runs/{run_id}", response_model=RunView, tags=["runs"])
    def get_run(run_id: str) -> RunView:
        return view(find_run(run_id))

    @app.get("/runs", response_model=list[RunView], tags=["runs"])
    def list_runs(limit: int = 50) -> list[RunView]:
        runs = sorted(manager.runs.values(), key=lambda r: r.created_at, reverse=True)
        return [view(r) for r in runs[: max(1, min(limit, 500))]]

    @app.delete("/runs/{run_id}", response_model=RunView, status_code=202, tags=["runs"])
    async def cancel_run(run_id: str) -> RunView:
        run = find_run(run_id)
        await manager.cancel(run)
        return view(run)

    @app.post(
        "/runs/{run_id}/answers",
        response_model=RunView,
        status_code=202,
        tags=["runs"],
        responses={
            409: {"description": "The run is not waiting for these answers"},
            422: {"description": "The answers do not fit the questions"},
        },
    )
    async def answer_run(run_id: str, body: AnswersBody) -> RunView:
        """Answer the questions a waiting run asked; the run then carries on."""
        run = find_run(run_id)
        try:
            manager.answer(run, body.batch, body.answers)
        except NotWaitingError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, f"Invalid answers: {exc}") from exc
        return view(run)

    @app.get(
        "/runs/{run_id}/events",
        tags=["runs"],
        response_class=EventSourceResponse,
        responses={200: {"description": "Server-sent events: status, progress, question, result"}},
    )
    async def run_events(run_id: str, request: Request) -> EventSourceResponse:
        run = find_run(run_id)
        last = request.headers.get("last-event-id", "0")
        after = int(last) if last.isdigit() else 0

        async def stream() -> AsyncIterator[dict[str, str]]:
            async for event in manager.events(run, after):
                yield {"id": str(event.seq), "event": event.kind, "data": json.dumps(event.data)}

        return EventSourceResponse(stream(), ping=15)

    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    if ui_root is not None:  # last, so every API route takes precedence
        app.mount("/", StaticFiles(directory=ui_root, html=True), name="ui")
    return app


def _bundled_ui() -> Path | None:
    """The web UI packed into the wheel at release time (absent in a source checkout)."""
    bundled = Path(__file__).parent / "ui"
    return bundled if (bundled / "index.html").is_file() else None


class _UIPages:
    """Send a browser's page loads (GET, asking for HTML) to the UI's index.html.

    The UI's pages share paths with the API (``/agents``, ``/runs/<id>``), so a page load gets
    the UI while the UI's own requests (JSON, events) reach the API. Plain ASGI on purpose:
    FastAPI's decorator middleware wraps every response, which stalls the live event stream.
    """

    API_PAGES = ("/docs", "/redoc", "/openapi.json")
    PAGE_HEADERS = {"Vary": "Accept", "Cache-Control": "no-cache"}

    def __init__(self, app: Any, root: Path) -> None:
        self.app = app
        self.root = root
        self.index = root / "index.html"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("method") == "GET":
            headers = dict(scope.get("headers") or [])
            accept = headers.get(b"accept", b"").decode("latin-1")
            path = str(scope.get("path", "/"))
            if "text/html" in accept and not path.startswith(self.API_PAGES):
                candidate = (self.root / path.lstrip("/")).resolve()
                if not (candidate.is_file() and self.root in candidate.parents):
                    # the page shares its URL with the API's JSON: without Vary the browser
                    # would answer the UI's own fetch of /runs/<id> with this cached page
                    page = FileResponse(self.index, headers=self.PAGE_HEADERS)
                    await page(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def _ui_root(ui_dir: Path) -> Path:
    root = ui_dir.resolve()
    if not (root / "index.html").is_file():
        raise RuntimeError(f"MARGIN_API_UI_DIR has no index.html: {root}")
    return root
