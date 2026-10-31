"""The HTTP API: routes, background runs, events (SSE), cancellation, queues and limits."""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from collections.abc import Iterator
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Any, ClassVar

import pytest
from echo_agent import EchoAgent
from fastapi.testclient import TestClient
from margin_api.app import create_app
from margin_api.files import FileStore, safe_name
from margin_api.settings import ApiSettings
from margin_core import (
    AgentInput,
    AgentRegistry,
    AgentResult,
    BaseAgent,
    Choice,
    Question,
    RunContext,
)
from margin_core.llm import LLMClient, create_llm
from margin_core.registry import ENTRY_POINT_GROUP
from pydantic import BaseModel, Field


class SlowInput(AgentInput):
    steps: int = 200
    fail: bool = False


class SlowOutput(BaseModel):
    steps: int


class Slow(BaseAgent):
    id = "slow"
    name = "Slow"
    description = "Counts slowly, checking for cancellation."
    version = "0.0.1"
    InputModel = SlowInput
    OutputModel = SlowOutput
    honours_cancel: ClassVar[bool] = True

    async def run(self, input: SlowInput, ctx: RunContext) -> AgentResult:
        if input.fail:
            raise RuntimeError("boom")
        for i in range(input.steps):
            if self.honours_cancel:
                ctx.check_cancelled()
            ctx.report_progress("count", f"step {i}", i / input.steps)
            await asyncio.sleep(0.01)
        return self.make_result(summary="counted", output=SlowOutput(steps=input.steps))


class Stubborn(Slow):
    id = "stubborn"
    honours_cancel = False


class Gpu(Slow):
    id = "gpu"
    uses_llm = True


class Asking(Gpu):
    """Asks a question first, then counts like Slow. Uses the GPU pool."""

    id = "asking"

    async def run(self, input: SlowInput, ctx: RunContext) -> AgentResult:
        go = Question(id="go", prompt="Go on?", choices=[Choice(value=True, label="Yes")])
        await ctx.ask([go], title="Check first")
        return await super().run(input, ctx)


class CopyInput(AgentInput):
    source: str = Field(json_schema_extra={"format": "file-path"})
    out: str | None = Field(default=None, json_schema_extra={"format": "output-dir"})


class CopyOutput(BaseModel):
    written: list[str]


class Copier(BaseAgent):
    """Reads a file (as an upload would give it) and writes a copy to its output folder."""

    id = "copier"
    name = "Copier"
    description = "Copies a file."
    version = "0.0.1"
    InputModel = CopyInput
    OutputModel = CopyOutput

    async def run(self, input: CopyInput, ctx: RunContext) -> AgentResult:
        written = []
        if input.out:
            target = Path(input.out) / "copy.txt"
            target.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(shutil.copyfile, input.source, target)
            written.append(str(target))
        return self.make_result(summary="copied", output=CopyOutput(written=written))


def _registry() -> AgentRegistry:
    broken = EntryPoint(name="broken", value="no_such_module:Agent", group=ENTRY_POINT_GROUP)
    registry = AgentRegistry([broken])
    for agent in (EchoAgent, Slow, Stubborn, Gpu, Asking, Copier):
        registry.register(agent)
    return registry


def no_model(provider: str | None, model: str | None) -> None:
    return None


def make_client(**overrides: Any) -> TestClient:
    settings = ApiSettings(**{"cancel_grace_s": 0.3, "max_body_bytes": 2000, **overrides})
    app = create_app(registry=_registry(), settings=settings, llm_factory=no_model)
    return TestClient(app, base_url="http://127.0.0.1")


@pytest.fixture
def client() -> Iterator[TestClient]:
    with make_client() as c:
        yield c


def wait_for(client: TestClient, run_id: str, statuses: set[str], timeout: float = 10) -> dict:  # type: ignore[type-arg]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/runs/{run_id}").json()
        if body["status"] in statuses:
            return body  # type: ignore[no-any-return]
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} never reached {statuses}: {body['status']}")


def start(client: TestClient, agent: str, body: dict[str, Any]) -> str:
    response = client.post(f"/agents/{agent}/runs", json=body)
    assert response.status_code == 202, response.text
    return response.json()["run_id"]  # type: ignore[no-any-return]


def sse(client: TestClient, run_id: str, last_id: str | None = None) -> list[dict[str, Any]]:
    headers = {"Last-Event-ID": last_id} if last_id else {}
    events: list[dict[str, str]] = []
    current: dict[str, str] = {}
    with client.stream("GET", f"/runs/{run_id}/events", headers=headers) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        for line in response.iter_lines():
            if not line:
                if current:
                    events.append(current)
                current = {}
            elif ":" in line and not line.startswith(":"):
                key, value = line.split(":", 1)
                current[key] = value.strip()
    return [
        {"id": int(e["id"]), "event": e["event"], "data": json.loads(e["data"])} for e in events
    ]


# ---- agents -----------------------------------------------------------------------------


def test_health(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"


def test_list_and_describe_agents(client: TestClient) -> None:
    body = client.get("/agents").json()
    assert [a["id"] for a in body["agents"]] == [
        "asking",
        "copier",
        "echo",
        "gpu",
        "slow",
        "stubborn",
    ]
    assert "broken" in body["load_errors"]
    echo = client.get("/agents/echo").json()
    assert echo["primary_input"] == "message" and echo["uses_llm"] is False
    assert echo["input_schema"]["required"] == ["message"]
    assert client.get("/agents/nope").status_code == 404
    broken = client.get("/agents/broken")
    assert broken.status_code == 500 and "failed to load" in broken.json()["detail"]


# ---- runs -------------------------------------------------------------------------------


def test_run_echo_end_to_end(client: TestClient) -> None:
    response = client.post("/agents/echo/runs", json={"message": "hi", "repeat": 2})
    assert response.status_code == 202
    created = response.json()
    assert created["links"]["events"] == f"/runs/{created['run_id']}/events"
    done = wait_for(client, created["run_id"], {"done"})
    assert done["result"]["status"] == "ok"
    assert done["result"]["data"]["echoed"] == "hi hi"
    assert done["finished_at"] is not None and done["queue_position"] is None
    assert any(r["run_id"] == created["run_id"] for r in client.get("/runs").json())


def test_bad_requests(client: TestClient) -> None:
    invalid = client.post("/agents/echo/runs", json={"message": "", "repeat": 99})
    assert invalid.status_code == 422 and "Invalid input" in invalid.json()["detail"]
    assert client.post("/agents/echo/runs", json={"message": "x", "nope": 1}).status_code == 422
    assert client.post("/agents/nope/runs", json={}).status_code == 404
    assert client.get("/runs/doesnotexist").status_code == 404


def test_agent_failure_is_a_result_not_an_http_error(client: TestClient) -> None:
    run_id = start(client, "slow", {"fail": True})
    done = wait_for(client, run_id, {"done"})
    assert done["result"]["status"] == "error"
    assert "RuntimeError: boom" in done["result"]["error"]


# ---- events -----------------------------------------------------------------------------


def test_events_replay_history_then_end_with_the_result(client: TestClient) -> None:
    run_id = start(client, "slow", {"steps": 5})
    wait_for(client, run_id, {"done"})
    events = sse(client, run_id)  # connects after the run finished: full history
    kinds = [e["event"] for e in events]
    assert kinds[0] == "status" and events[0]["data"] == {"status": "queued"}
    assert kinds.count("progress") == 5 and kinds[-1] == "result"
    assert [e["id"] for e in events] == sorted(e["id"] for e in events)
    assert events[-1]["data"]["result"]["data"] == {"steps": 5}

    resumed = sse(client, run_id, last_id=str(events[3]["id"]))
    assert [e["id"] for e in resumed] == [e["id"] for e in events[4:]]


def test_events_stream_live(client: TestClient) -> None:
    run_id = start(client, "slow", {"steps": 30})
    events = sse(client, run_id)  # connects while queued or running
    assert events[-1]["event"] == "result"
    assert sum(e["event"] == "progress" for e in events) == 30


# ---- cancellation and queues ------------------------------------------------------------


def test_cancel_a_running_run(client: TestClient) -> None:
    run_id = start(client, "slow", {"steps": 2000})
    wait_for(client, run_id, {"running"})
    assert client.delete(f"/runs/{run_id}").status_code == 202
    done = wait_for(client, run_id, {"cancelled"})
    assert done["result"]["error"] == "Run was cancelled"
    assert client.delete(f"/runs/{run_id}").json()["status"] == "cancelled"  # idempotent


def test_a_run_that_ignores_cancellation_is_stopped_after_the_grace_period(
    client: TestClient,
) -> None:
    run_id = start(client, "stubborn", {"steps": 2000})
    wait_for(client, run_id, {"running"})
    client.delete(f"/runs/{run_id}")
    done = wait_for(client, run_id, {"cancelled"}, timeout=5)
    assert done["result"] is None  # the task was stopped before the agent returned


def test_llm_runs_queue_one_at_a_time() -> None:
    with make_client(llm_concurrency=1) as client:
        first = start(client, "gpu", {"steps": 2000})
        second = start(client, "gpu", {"steps": 5})
        wait_for(client, first, {"running"})
        queued = client.get(f"/runs/{second}").json()
        assert queued["status"] == "queued" and queued["queue_position"] == 1
        other = start(client, "slow", {"steps": 5})  # other pool: not blocked by the GPU
        assert wait_for(client, other, {"done"})["result"]["status"] == "ok"

        assert client.delete(f"/runs/{second}").json()["status"] == "cancelled"  # while queued
        client.delete(f"/runs/{first}")
        wait_for(client, first, {"cancelled"})


# ---- questions --------------------------------------------------------------------------


def answer(client: TestClient, run_id: str, answers: dict[str, Any], batch: str | None = None):  # type: ignore[no-untyped-def]
    if batch is None:
        batch = client.get(f"/runs/{run_id}").json()["question"]["id"]
    return client.post(f"/runs/{run_id}/answers", json={"batch": batch, "answers": answers})


def test_a_run_waits_for_answers_then_carries_on(client: TestClient) -> None:
    run_id = start(client, "echo", {"message": "hi", "ask": True})
    waiting = wait_for(client, run_id, {"waiting"})
    question = waiting["question"]
    assert question["title"] == "Before echoing"
    assert [q["id"] for q in question["questions"]] == ["style"]
    assert question["questions"][0]["evidence"][0]["detail"] == "message: hi"
    assert waiting["last_event"] >= 4  # queued, running, waiting, question

    response = answer(client, run_id, {"style": "capitals"})
    assert response.status_code == 202, response.text
    done = wait_for(client, run_id, {"done"})
    assert done["question"] is None
    assert done["result"]["data"]["echoed"] == "HI"
    (given,) = done["result"]["metadata"]["answers"]
    assert given["source"] == "user" and given["label"] == "In capitals"

    events = sse(client, run_id)
    statuses = [e["data"]["status"] for e in events if e["event"] == "status"]
    assert statuses == ["queued", "running", "waiting", "queued", "running", "done"]
    (asked,) = [e for e in events if e["event"] == "question"]
    assert asked["data"]["id"] == question["id"]


def test_answers_that_do_not_fit_are_refused(client: TestClient) -> None:
    run_id = start(client, "echo", {"message": "hi", "ask": True})
    waiting = wait_for(client, run_id, {"waiting"})
    batch = waiting["question"]["id"]

    wrong = answer(client, run_id, {"style": "sideways"}, batch)
    assert wrong.status_code == 422 and "not one of the choices" in wrong.json()["detail"]
    assert answer(client, run_id, {"nope": 1}, batch).status_code == 422
    assert answer(client, run_id, {}, "an-old-batch").status_code == 409
    assert client.get(f"/runs/{run_id}").json()["status"] == "waiting"  # nothing changed

    assert answer(client, run_id, {}, batch).status_code == 202  # left out: the default
    done = wait_for(client, run_id, {"done"})
    assert done["result"]["data"]["echoed"] == "hi"
    assert done["result"]["metadata"]["answers"][0]["source"] == "default"
    assert answer(client, run_id, {}, batch).status_code == 409  # not waiting any more
    assert client.post("/runs/nope/answers", json={"batch": "x"}).status_code == 404


def test_a_waiting_run_gives_its_place_to_others() -> None:
    with make_client(llm_concurrency=1) as client:
        asking = start(client, "asking", {"steps": 5})
        wait_for(client, asking, {"waiting"})
        # the single GPU place is free while it waits
        other = start(client, "gpu", {"steps": 5})
        assert wait_for(client, other, {"done"})["result"]["status"] == "ok"

        busy = start(client, "gpu", {"steps": 2000})
        wait_for(client, busy, {"running"})
        assert answer(client, asking, {"go": True}).status_code == 202
        requeued = wait_for(client, asking, {"queued"})
        assert requeued["queue_position"] == 1  # back in line behind the busy run

        client.delete(f"/runs/{busy}")
        done = wait_for(client, asking, {"done"})
        assert done["result"]["status"] == "ok" and done["result"]["data"] == {"steps": 5}


def test_a_waiting_run_can_be_cancelled(client: TestClient) -> None:
    run_id = start(client, "asking", {"steps": 5})
    wait_for(client, run_id, {"waiting"})
    assert client.delete(f"/runs/{run_id}").status_code == 202
    done = wait_for(client, run_id, {"cancelled"}, timeout=3)
    assert done["question"] is None


def test_a_question_nobody_answers_stops_the_run() -> None:
    with make_client(answer_timeout_s=0.2) as client:
        run_id = start(client, "asking", {"steps": 5})
        done = wait_for(client, run_id, {"done"})
        assert done["result"]["status"] == "error"
        assert "No answer came within 0.2 seconds" in done["result"]["error"]
        # it no longer holds anything: another GPU run goes straight through
        other = start(client, "gpu", {"steps": 1})
        assert wait_for(client, other, {"done"})["result"]["status"] == "ok"


# ---- limits and housekeeping ------------------------------------------------------------


def test_request_body_limit(client: TestClient) -> None:
    big = {"message": "x" * 5000}
    response = client.post("/agents/echo/runs", json=big)
    assert response.status_code == 413
    chunked = client.post(
        "/agents/echo/runs",
        content=iter([json.dumps(big).encode()]),
        headers={"content-type": "application/json"},
    )
    assert chunked.status_code == 413


def test_cors_allows_configured_origins_only(client: TestClient) -> None:
    allowed = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:3000"
    denied = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in denied.headers


def test_finished_runs_expire() -> None:
    with make_client(result_ttl_s=0.0) as client:
        run_id = start(client, "echo", {"message": "hi"})
        wait_for(client, run_id, {"done"})
        deadline = time.monotonic() + 5  # the sweeper runs at most once a second
        while client.get(f"/runs/{run_id}").status_code != 404:
            assert time.monotonic() < deadline, "finished run was never removed"
            time.sleep(0.1)


def test_api_works_when_no_model_can_be_created() -> None:
    def broken_factory(provider: str | None, model: str | None) -> None:
        raise RuntimeError("no API key")

    settings = ApiSettings()
    app = create_app(registry=_registry(), settings=settings, llm_factory=broken_factory)
    with TestClient(app, base_url="http://127.0.0.1") as client:
        run_id = start(client, "echo", {"message": "hi"})
        assert wait_for(client, run_id, {"done"})["result"]["status"] == "ok"


# ---- model settings, per-run models, host check --------------------------------------


def factory(provider: str | None, model: str | None) -> LLMClient | None:
    return create_llm(provider, model)  # real factory: mock works, hosted ones need keys


@pytest.fixture
def settings_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("MARGIN_CONFIG_FILE", str(tmp_path / "settings.json"))
    registry = AgentRegistry([])
    registry.register(Gpu)
    app = create_app(registry=registry, settings=ApiSettings(), llm_factory=factory)
    with TestClient(app, base_url="http://127.0.0.1") as c:
        yield c


def test_requests_for_other_hosts_are_refused(settings_client: TestClient) -> None:
    assert settings_client.get("/health").status_code == 200
    assert settings_client.get("/health", headers={"host": "evil.example"}).status_code == 400


def test_settings_show_sources_and_never_the_keys(settings_client: TestClient) -> None:
    view = settings_client.get("/settings/llm").json()
    assert view["provider"] == "local" and view["provider_source"] == "default"
    assert view["saving_enabled"]
    assert {p["id"] for p in view["providers"]} == {"local", "anthropic", "openai"}

    saved = settings_client.put("/settings/llm", json={
        "provider": "anthropic",
        "keys": {"anthropic": "sk-ant-secret-1234"},
        "models": {"anthropic": "claude-test"},
    }).json()  # fmt: skip
    anthropic = next(p for p in saved["providers"] if p["id"] == "anthropic")
    assert saved["provider"] == "anthropic" and saved["provider_source"] == "saved"
    assert anthropic["key_set"] and anthropic["key_hint"] == "…1234"
    assert anthropic["model"] == "claude-test"
    assert (
        "sk-ant-secret" not in settings_client.get("/settings/llm").text
    )  # the key never comes back

    cleared = settings_client.put("/settings/llm", json={"keys": {"anthropic": ""}}).json()
    assert not next(p for p in cleared["providers"] if p["id"] == "anthropic")["key_set"]


def test_settings_reject_bad_input(settings_client: TestClient) -> None:
    assert (
        settings_client.put("/settings/llm", json={"local_base_url": "ftp://x"}).status_code == 422
    )
    assert settings_client.put("/settings/llm", json={"provider": "nope"}).status_code == 422
    assert settings_client.put("/settings/llm", json={"github_token": "x"}).status_code == 422


def test_saving_turned_off_is_reported(
    settings_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MARGIN_CONFIG_FILE", "")
    assert settings_client.put("/settings/llm", json={"provider": "openai"}).status_code == 409


def test_a_run_can_choose_its_model(settings_client: TestClient) -> None:
    created = settings_client.post("/agents/gpu/runs?provider=mock&model=m1", json={"steps": 1})
    assert created.status_code == 202
    run = wait_for(settings_client, created.json()["run_id"], {"done"})
    assert run["llm"] == {"provider": "mock", "model": "m1"}

    # an explicit choice that cannot work is refused up front, with the reason
    refused = settings_client.post("/agents/gpu/runs?provider=anthropic", json={"steps": 1})
    assert refused.status_code == 422 and "API key" in refused.json()["detail"]


def test_hosted_runs_do_not_wait_for_the_local_gpu(settings_client: TestClient) -> None:
    local = start(settings_client, "gpu", {"steps": 300})  # holds the single local slot
    hosted = settings_client.post("/agents/gpu/runs?provider=mock", json={"steps": 1}).json()
    assert wait_for(settings_client, hosted["run_id"], {"done"})["status"] == "done"
    assert settings_client.get(f"/runs/{local}").json()["status"] == "running"  # still going
    settings_client.delete(f"/runs/{local}")


def test_settings_changes_apply_to_the_next_run(settings_client: TestClient) -> None:
    settings_client.put("/settings/llm", json={"provider": "openai"})
    # no OpenAI key: the default provider cannot be used, so the run goes ahead without
    # a model (the agent reports that) rather than failing the request
    run_id = start(settings_client, "gpu", {"steps": 1})
    assert wait_for(settings_client, run_id, {"done"})["llm"]["provider"] == "openai"


# ---- serving the built UI --------------------------------------------------------------


def test_serves_the_ui_alongside_the_api(tmp_path: Path) -> None:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>margin ui</html>", encoding="utf-8")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    settings = ApiSettings(ui_dir=str(tmp_path))
    app = create_app(registry=_registry(), settings=settings, llm_factory=no_model)
    page = {"accept": "text/html,application/xhtml+xml"}
    with TestClient(app, base_url="http://127.0.0.1") as c:
        assert "margin ui" in c.get("/", headers=page).text
        deep = c.get("/runs/abc123", headers=page)
        assert "margin ui" in deep.text  # a deep link loads the UI
        # ...and is never reused for the UI's own JSON request to the same URL
        assert deep.headers["vary"] == "Accept"
        assert deep.headers["cache-control"] == "no-cache"
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/agents").json()["agents"]  # the UI's own requests still reach the API
        assert c.get("/runs/abc123").status_code == 404
        assert "swagger" in c.get("/docs", headers=page).text.lower()  # API docs stay reachable
        assert c.get("/../pyproject.toml", headers=page).status_code in (200, 404)
        assert "margin ui" in c.get("/%2e%2e/secret", headers=page).text  # no escape from ui_dir
        # a download link asks for HTML too, but must get the file, not the UI
        path = c.post("/uploads?name=a.txt", content=b"hello").json()["path"]
        run_id = start(c, "copier", {"source": path})
        wait_for(c, run_id, {"done"})
        assert c.get(f"/runs/{run_id}/files/copy.txt", headers=page).content == b"hello"


def test_ui_dir_without_index_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="index.html"):
        create_app(
            registry=_registry(), settings=ApiSettings(ui_dir=str(tmp_path)), llm_factory=no_model
        )


def test_live_events_still_stream_when_the_ui_is_served(tmp_path: Path) -> None:
    # regression: a decorator middleware for UI page loads stalled the event stream
    (tmp_path / "index.html").write_text("<html>ui</html>", encoding="utf-8")
    app = create_app(
        registry=_registry(), settings=ApiSettings(ui_dir=str(tmp_path)), llm_factory=no_model
    )
    with TestClient(app, base_url="http://127.0.0.1") as c:
        run_id = start(c, "echo", {"message": "hi"})
        with c.stream(
            "GET", f"/runs/{run_id}/events", headers={"accept": "text/event-stream"}
        ) as events:
            body = "".join(events.iter_text())
        assert "event: result" in body


# ---- uploads and run files -----------------------------------------------------------------


@pytest.fixture
def files_client(tmp_path: Path) -> Iterator[TestClient]:
    with make_client(files_dir=str(tmp_path), max_upload_bytes=10_000) as c:
        yield c


def test_an_uploaded_file_is_read_and_the_run_files_downloaded(
    files_client: TestClient, tmp_path: Path
) -> None:
    data = b"a,b\n1,2\n" * 300  # bigger than max_body_bytes: uploads have their own limit
    up = files_client.post("/uploads?name=sales.csv", content=data)
    assert up.status_code == 201, up.text
    saved = Path(up.json()["path"])
    assert up.json()["name"] == "sales.csv" and up.json()["size"] == len(data)
    assert saved.read_bytes() == data and tmp_path / "uploads" in saved.parents

    run_id = start(files_client, "copier", {"source": str(saved)})
    view = wait_for(files_client, run_id, {"done"})
    assert view["files"] == [{"name": "copy.txt", "size": len(data)}]
    download = files_client.get(f"/runs/{run_id}/files/copy.txt")
    assert download.content == data
    assert "attachment" in download.headers["content-disposition"]


def test_an_output_folder_given_with_the_run_is_left_alone(
    files_client: TestClient, tmp_path: Path
) -> None:
    source = tmp_path / "in.txt"
    source.write_text("x")
    run_id = start(files_client, "copier", {"source": str(source), "out": str(tmp_path / "mine")})
    view = wait_for(files_client, run_id, {"done"})
    assert (tmp_path / "mine" / "copy.txt").exists()
    assert view["files"] == []  # only the run's own folder is served


def test_uploads_over_the_limit_or_empty_are_refused_and_not_kept(
    files_client: TestClient, tmp_path: Path
) -> None:
    assert files_client.post("/uploads?name=big.csv", content=b"x" * 10_001).status_code == 413

    def chunks() -> Iterator[bytes]:  # no content-length: the limit holds while streaming
        for _ in range(20):
            yield b"x" * 1000

    assert files_client.post("/uploads?name=big.csv", content=chunks()).status_code == 413
    assert files_client.post("/uploads?name=empty.csv", content=b"").status_code == 422
    assert list((tmp_path / "uploads").iterdir()) == []


def test_upload_names_cannot_leave_the_upload_folder(
    files_client: TestClient, tmp_path: Path
) -> None:
    up = files_client.post("/uploads", params={"name": "../../evil.txt"}, content=b"x").json()
    assert up["name"] == "evil.txt"
    assert (tmp_path / "uploads") in Path(up["path"]).parents
    assert safe_name("..\\a\\b.csv") == "b.csv"
    assert safe_name("sales; rm -rf.csv") == "sales_ rm -rf.csv"
    assert safe_name("مبيعات.xlsx") == "مبيعات.xlsx"  # letters of any script are kept
    assert safe_name("..") == "upload"


def test_only_a_runs_own_files_can_be_downloaded(files_client: TestClient, tmp_path: Path) -> None:
    (tmp_path / "secret.txt").write_text("no")
    source = tmp_path / "in.txt"
    source.write_text("x")
    run_id = start(files_client, "copier", {"source": str(source)})
    wait_for(files_client, run_id, {"done"})
    for name in ("../../secret.txt", "..%2F..%2Fsecret.txt", "nope.txt", "copy.txt.bak"):
        assert files_client.get(f"/runs/{run_id}/files/{name}").status_code == 404, name
    assert files_client.get("/runs/unknown/files/copy.txt").status_code == 404


def test_files_go_when_their_run_or_upload_expires(tmp_path: Path) -> None:
    with make_client(files_dir=str(tmp_path), result_ttl_s=0.0) as c:
        up = Path(c.post("/uploads?name=a.txt", content=b"x").json()["path"])
        run_id = start(c, "copier", {"source": str(up)})
        wait_for(c, run_id, {"done"})
        assert (tmp_path / "runs" / run_id / "copy.txt").exists()
        time.sleep(0.05)
        c.app.state.manager.sweep()  # type: ignore[attr-defined]
        assert not (tmp_path / "runs" / run_id).exists()
        assert not up.exists()


def test_the_file_store_removes_only_a_folder_it_made(tmp_path: Path) -> None:
    given = FileStore(str(tmp_path))
    given.close()
    assert tmp_path.exists()
    own = FileStore()
    own.close()
    assert not own.root.exists()
