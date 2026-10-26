# Writing an agent

This guide covers everything a new agent needs: creating it, the code, tests, the README,
and how it is published as its own repository.

## 1. What an agent is

An agent is a small package under `agents/` that does one job. Every agent:

- subclasses `BaseAgent` from `margin_core` and implements one async method, `run`;
- declares typed input and output models (Pydantic);
- returns an `AgentResult`: a short summary, findings backed by evidence, and its own data;
- imports only from `margin_core`, never from another agent;
- is a self-contained sub-repo: its folder has everything it needs and refers to nothing
  outside itself, so it can be mirrored to its own GitHub repository.

## 2. Create it with the scaffolder

Never copy another agent by hand. Run:

```bash
uv run python scripts/new_agent.py license-checker \
    --name "License Checker" \
    --description "Finds incompatible licence combinations in a repository."
uv sync --all-packages
uv run pytest agents/license_checker
```

The id must be kebab-case; the folder and Python package use the same name with
underscores. The scaffolder creates a working stub agent and also wires it into the
workspace (root `pyproject.toml` and the agents table in the main README).

## 3. The folder layout

```text
agents/license_checker/
├── pyproject.toml        package metadata, entry point, [tool.margin]
├── README.md             required sections (see section 7)
├── CHANGELOG.md          one entry per version
├── LICENSE               copy of the root licence
├── src/license_checker/
│   ├── __init__.py       exports the agent, its models and __version__
│   ├── py.typed
│   ├── agent.py          the BaseAgent subclass
│   └── models.py         input and output models
└── tests/
    └── test_agent.py
```

`scripts/check_agents.py` enforces this layout in CI.

### `[tool.margin]`

```toml
[tool.margin]
id = "license-checker"
stage = "planned"            # planned | experimental | stable
# mirror = "Waddah0-0/margin-license-checker"
```

- `planned`: a scaffold or work in progress. `agent.py` and `models.py` are optional, and
  the agent is never mirrored.
- `experimental`: it works but may change. It can be mirrored.
- `stable`: tested and documented.

Agent `pyproject.toml` files must not contain `[tool.uv.sources]`: the root `pyproject.toml`
provides it for every package, and a per-agent copy would break the mirror repository.

## 4. Models and the agent class

```python
# models.py
from margin_core import AgentInput
from pydantic import BaseModel, Field


class LicenseCheckerInput(AgentInput):
    target: str = Field(description="GitHub URL or local path.")
    paths: list[str] | None = Field(default=None, description="Restrict to these paths.")


class LicenseCheckerOutput(BaseModel):
    licences: dict[str, int]
```

```python
# agent.py
from margin_core import AgentResult, BaseAgent, Evidence, Finding, RunContext

from license_checker.models import LicenseCheckerInput, LicenseCheckerOutput


class LicenseCheckerAgent(BaseAgent):
    id = "license-checker"
    name = "License Checker"
    description = "Finds incompatible licence combinations in a repository."
    version = "0.1.0"
    InputModel = LicenseCheckerInput
    OutputModel = LicenseCheckerOutput
    primary_input = "target"  # what `margin run license-checker <value>` fills

    async def run(self, input: LicenseCheckerInput, ctx: RunContext) -> AgentResult:
        async with await ctx.load_workspace(input.target, paths=input.paths) as ws:
            counts: dict[str, int] = {}
            for i, file in enumerate(ws.files):
                ctx.check_cancelled()
                ctx.report_progress("scan", file.path, i / max(len(ws.files), 1))
                ...  # the real work
        return self.make_result(
            summary=f"Found {len(counts)} licences.",
            output=LicenseCheckerOutput(licences=counts),
            findings=[
                Finding(
                    title="GPL code in an MIT project",
                    summary="...",
                    evidence=[Evidence(kind="file", location="vendor/x.c:1-20", detail="...")],
                )
            ],
        )
```

The services available on `ctx`:

| Call | Use it to |
|---|---|
| `await ctx.load_workspace(target, paths=..., branch=...)` | Load a GitHub URL or local path safely. Use it with `async with`, so temporary clones are deleted. Its warnings are added to the result automatically. |
| `ctx.report_progress(stage, message, fraction)` | Drive the CLI progress display and the API's live events. |
| `ctx.check_cancelled()` | Stop promptly when the user cancels. Call it between expensive steps. |
| `ctx.warn(message)` | Add a warning to the result, e.g. "3 files could not be parsed". |
| `ctx.require_llm()` | Get this run's model session, or fail clearly if none is configured. |
| `await ctx.ask(questions, title=...)` | Stop and ask the person running the agent. See [Asking questions](#asking-questions). |

### Results and status

Return results with `self.make_result(...)`, which validates `output` against
`OutputModel`.

- `status="ok"`: everything requested was done.
- `status="partial"`: the result is usable, but some work was skipped (a budget or time limit
  was hit, some files were unreadable). Add a warning for each skipped part.
- Errors: just raise. `execute()` turns any exception into a `status="error"` result.

### Using a model

`ctx.require_llm()` returns a session that belongs to this run only. Its usage, its warnings
(for example "prompt probably truncated") and its budget (`RunContext.max_cost_usd`) are
separate from other runs, and they are copied into the result's metadata automatically.

```python
verdict = await ctx.require_llm().complete_structured(Verdict, prompt, system=RUBRIC)
```

`complete_structured` passes the schema to the server, so local models are constrained to
valid JSON. The default model is local (Ollama, `qwen3.5:9b`), with a context window that
may be as small as 8,192 tokens. Keep prompts well under it, and expect each call to take
seconds.

### Asking questions

When an agent cannot decide something from the input alone, such as which date format a
column uses, it should ask instead of guessing. `ctx.ask` pauses the run, puts the
questions to the person running it, and returns the answers:

```python
from margin_core import AnswersInput, Choice, Evidence, Question


class CleanerInput(AnswersInput):  # adds the standard `answers` and `assume_defaults` fields
    path: str


answers = await ctx.ask(
    [
        Question(
            id="date_format:order_date",
            prompt="Which date format does order_date use?",
            detail="Every day and month in it is 12 or less, so both readings are possible.",
            choices=[
                Choice(value="mdy", label="MM/DD/YYYY"),
                Choice(value="dmy", label="DD/MM/YYYY"),
            ],
            default="mdy",
            evidence=[
                Evidence(kind="sample", location="order_date", detail="01/02/2024, 03/04/2024")
            ],
        ),
    ],
    title="Check the cleaning plan",
    preset=input.answers,
    assume_defaults=input.assume_defaults,
)
fmt = answers["date_format:order_date"].value
```

- Ask everything you need at one point in one call. The person answers once, not once per
  question.
- Question kinds: `choice` (one of `choices`, or any text with `allow_other=True`),
  `multi_choice` (a list of them) and `text`. Give a `default` whenever there is a sensible
  one; it is shown as the suggestion. Attach the `evidence` that made you ask.
- How the question reaches a person depends on where the agent runs. `margin run` asks in
  the terminal. The API sets the run to `waiting` and the web UI shows a form. A Python
  caller passes a `responder` to `RunContext`.
- When there is nobody to ask (a script, CI, `assume_defaults=true`), every question takes
  its default. The result records it as not confirmed and adds a warning. A required
  question without a default then fails the run with `NoAnswerError`, so give such questions
  a default, or tell users to answer them up front.
- Answers given in the `answers` input field are not asked. Every answer, with who gave it
  (`user`, `preset` or `default`), is kept in `result.metadata.answers`, and the reports
  list them. Use stable ids, so a run can be repeated with the same answers.

## 5. Tests

Tests never use the network. Use `MockLLM` for models and build git repositories inside
the test when you need history.

```python
from margin_core.llm import MockLLM
from license_checker import LicenseCheckerAgent


async def test_reports_licences(tmp_path) -> None:
    (tmp_path / "LICENSE").write_text("MIT License ...", encoding="utf-8")
    result = await LicenseCheckerAgent(llm=MockLLM(["{}"])).execute({"target": str(tmp_path)})
    assert result.status == "ok"
```

Test fixtures live in the agent's `tests/` folder. Third-party code is never copied in.

## 6. Versions and the changelog

The version appears in three places and they must match: `pyproject.toml`,
`__version__` in `__init__.py`, and the class's `version`. Every version has a
`## [x.y.z]` entry in `CHANGELOG.md`.

## 7. The README

Every agent README has these sections, in this order:

1. **What it does**: the problem it solves and for whom.
2. **How it works**: the steps, in plain words.
3. **Input**: a table of fields; mark the primary input.
4. **Output**: what `data` contains and which findings it reports.
5. **Limits**: what it cannot do and when not to trust it.
6. **Usage**: a command or a short Python example.
7. **Development**: where it lives in the monorepo and how to run its tests.

Links must be absolute (`https://github.com/...`) or stay inside the agent folder. Links
like `../../docs` break in the mirror repository. Add a row for the agent to the agents
table in the main README; the scaffolder does this for you.

## 8. Checks

Before committing, run everything CI runs:

```bash
uv run ruff check .
uv run ruff format --check .
uv run python scripts/typecheck.py
uv run python scripts/check_agents.py
uv run pytest
```

## 9. Publishing as its own repository

Once the agent does real work, set `stage = "experimental"` and add the `mirror` key. After
CI passes on `main`, the mirror workflow copies the agent folder, with its own history, to
`<owner>/margin-<id>`. The mirror is read-only; all changes happen in this repository.
The mirror repository must exist and the `MIRROR_TOKEN` secret must give access to it
before the first mirror.
