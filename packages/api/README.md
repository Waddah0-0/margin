# margin-api

The web UI and HTTP API for margin. It runs your installed agents in the background, so you
can start a run, watch its progress live and read the result with all its evidence, in the
browser or from any program that speaks HTTP.

## Starting it

```bash
pip install margin-api margin-ai-code-detector
margin-api                   # open http://127.0.0.1:8000 (API docs at /docs)
```

The web UI comes inside the package, so that one address is the whole app. The server only
listens on `127.0.0.1`, which means nothing else on your network can reach it. You can change
that and a few other things with `MARGIN_API_` environment variables (or a `.env` file):

| Setting | Default | Meaning |
|---|---|---|
| `MARGIN_API_HOST` / `MARGIN_API_PORT` | `127.0.0.1` / `8000` | Where to listen. Change the host only if you mean to expose it. |
| `MARGIN_API_ALLOWED_HOSTS` | `["127.0.0.1", "localhost"]` | Host names the API answers to. This blocks DNS-rebinding attacks from web pages; add your host name if you expose the API. |
| `MARGIN_API_CORS_ORIGINS` | `["http://localhost:3000", "http://127.0.0.1:3000"]` | Web pages allowed to call it (JSON list). |
| `MARGIN_API_LLM_CONCURRENCY` | `1` | Runs of agents that use a model, at once (one local GPU). |
| `MARGIN_API_OTHER_CONCURRENCY` | `4` | Runs of other agents, at once. |
| `MARGIN_API_RESULT_TTL_S` | `3600` | Seconds a finished run is kept. |
| `MARGIN_API_MAX_BODY_BYTES` | `1000000` | Largest accepted request body. |
| `MARGIN_API_CANCEL_GRACE_S` | `30` | Time a cancelled run gets to stop on its own before it is stopped. |
| `MARGIN_API_ANSWER_TIMEOUT_S` | `3600` | How long a run waits for answers to its questions before it stops. |

Model settings (`DEFAULT_LLM_PROVIDER`, `LOCAL_LLM_BASE_URL`, ...) are the same as for the CLI.

## Endpoints

| Method and path | What it does |
|---|---|
| `GET /health` | Liveness check. |
| `GET /agents` | Installed agents with their input and output JSON schemas, plus any that failed to load. |
| `GET /agents/{id}` | One agent. |
| `POST /agents/{id}/runs` | Start a run. The body is the agent's input as JSON; `?provider=` and `?model=` choose the model for this run only. Answers `202` with the `run_id`. |
| `GET /runs/{run_id}` | Status (`queued`, `running`, `waiting`, `done`, `cancelled`), queue position, latest progress, the open questions while `waiting` and, when done, the result. |
| `GET /runs/{run_id}/events` | Server-sent events: `status`, `progress`, `question` when the agent asks something, then one final `result`. |
| `POST /runs/{run_id}/answers` | Answer a waiting run: `{"batch": "<question.id>", "answers": {"<question id>": value}}`. A question left out takes its default. `422` if an answer does not fit, `409` if the run is not waiting for these questions. |
| `DELETE /runs/{run_id}` | Cancel a run. |
| `GET /runs` | Recent runs. |
| `GET /settings/llm` | Model settings: the provider in use, each provider's model, whether a key is set (with its last four characters, never the key), and where each value comes from. |
| `PUT /settings/llm` | Save model settings (provider, models, keys, local server address, spending limit). Applies from the next run. |
| `GET /settings/llm/models?provider=` | The models the provider offers right now, asked live. |
| `POST /settings/llm/test` | Send one tiny prompt and report whether, and how fast, the model answered. |

## Example with curl

```bash
# start a run
curl -s -X POST http://127.0.0.1:8000/agents/ai-code-detector/runs \
     -H 'content-type: application/json' -d '{"target": "https://github.com/psf/requests"}'
# -> {"run_id": "342e1c...", "status": "queued", "queue_position": 1, "links": {...}}

# follow it live (the stream ends with a "result" event)
curl -N http://127.0.0.1:8000/runs/342e1c.../events

# or poll it, or cancel it
curl -s http://127.0.0.1:8000/runs/342e1c...
curl -s -X DELETE http://127.0.0.1:8000/runs/342e1c...
```

## How runs behave

Starting a run returns straight away with a `run_id`; the work happens in the background.

Runs that use a local model wait in one queue and go one at a time, since a local model
usually has a single GPU to work with. Runs on Anthropic or OpenAI skip that queue, and agents
that use no model run up to four at once. While a run waits, it reports its place in line.

Each run keeps its last 200 events, and the event stream replays them before going live, so
you can connect late without missing anything. If the connection drops, reconnect with the
standard `Last-Event-ID` header and the stream picks up where it stopped.

When an agent fails, the run still finishes as `done`; the failure is in its result
(`status: "error"`, with the reason). HTTP errors are for bad requests: `404` for an unknown
agent or run, `422` for input that doesn't match the agent's schema, `413` for a body that's
too large, and `500` for an agent that failed to load.

Some agents stop to ask a question. The run then moves to `waiting`, sends a `question`
event, and its `GET /runs/{run_id}` view carries the questions. A waiting run gives up its
place in the queue, so a question nobody answers never holds the GPU. Once you post the
answers it goes back to `queued` and continues when a place is free. A run nobody answers
stops after an hour (`MARGIN_API_ANSWER_TIMEOUT_S`) with an error result.

```bash
curl -s -X POST http://127.0.0.1:8000/runs/342e1c.../answers \
     -H 'content-type: application/json' \
     -d '{"batch": "9f2c...", "answers": {"style": "capitals"}}'
```

Cancelling asks the agent to stop at its next checkpoint. A model call already under way is
allowed to finish, and an agent that still hasn't stopped after the grace period is stopped.
A waiting run stops at once.

Runs live in memory. They're gone after an hour, or when the server restarts, so export a
result if you want to keep it.

## Working on the UI

In a source checkout, `scripts/export_openapi.py` writes the OpenAPI schema to
`ui/openapi.json`, and the UI's typed client is generated from it. CI fails if the file is
out of date.
