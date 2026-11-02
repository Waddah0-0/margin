# margin-core

The shared core of [margin](https://github.com/Waddah0-0/margin), a collection of small AI
agents that answer with evidence. You need this package to write an agent. To use one,
install the agent (for example `margin-ai-code-detector`) together with `margin-cli` or
`margin-api`.

```bash
pip install margin-core
```

## What's in it

An agent is a class with an input model, an output model and an async `run` method. You call
it through `execute()`, which validates the input, times the run, counts model usage, and
turns a crash into an error result instead of an exception. Every agent returns the same
`AgentResult`: a summary, findings, the evidence for each finding, warnings, and whatever
typed data the agent wants to add.

Agents register under the `margin.agents` entry point, so installing one is all it takes for
the CLI, the API and the web UI to find it.

The model client gives you one interface to local OpenAI-compatible servers (Ollama, LM
Studio, llama.cpp, vLLM), Anthropic and OpenAI. It retries, tracks tokens and cost, and stops
at a spending limit you set. `MockLLM` returns canned answers, which keeps tests offline.

The loaders turn a local folder or a GitHub repository into a `Workspace`: the files worth
reading, the files that were skipped and why, and the git history. A repository is
size-checked before it is cloned, and nothing in it is ever run.

## A minimal agent

```python
from pydantic import BaseModel
from margin_core import AgentInput, AgentResult, BaseAgent, RunContext


class GreetInput(AgentInput):
    name: str


class GreetOutput(BaseModel):
    greeting: str


class Greeter(BaseAgent):
    id = "greeter"
    name = "Greeter"
    description = "Says hello."
    version = "0.1.0"
    InputModel = GreetInput
    OutputModel = GreetOutput

    async def run(self, input: GreetInput, ctx: RunContext) -> AgentResult:
        greeting = f"Hello, {input.name}!"
        return self.make_result(summary=greeting, output=GreetOutput(greeting=greeting))
```

Register it in your package's `pyproject.toml`:

```toml
[project.entry-points."margin.agents"]
greeter = "my_package.agent:Greeter"
```

The full guide is
[docs/writing-an-agent.md](https://github.com/Waddah0-0/margin/blob/main/docs/writing-an-agent.md).

## Settings

Model settings are read from environment variables first, then from settings saved in the
web UI, then from the file named by `MARGIN_ENV_FILE` (a `.env` in the current folder is not
read, because it may belong to a repository being analysed). The ones you are likely to need
are `DEFAULT_LLM_PROVIDER`
(`local`, `anthropic` or `openai`), `LOCAL_LLM_BASE_URL`, `LOCAL_LLM_MODEL`,
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and `MAX_COST_USD`.
[.env.example](https://github.com/Waddah0-0/margin/blob/main/.env.example) lists them all.

## License

MIT
