"""The ``agents`` command: list, inspect and run installed agents.

Output conventions: the report (or the ``--json`` listing) goes to stdout and nothing else
does, so ``margin run ... --format json > report.json`` always produces valid JSON. Progress,
warnings and errors go to stderr.

Exit codes:

====  =====================================================================
0     the run finished with status ``ok`` (or ``partial`` without ``--strict``)
1     the run finished with status ``error``
2     bad usage or invalid input
3     the agent is not installed or failed to load
4     the run finished with status ``partial`` and ``--strict`` was given
130   cancelled with Ctrl+C
====  =====================================================================
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from enum import IntEnum, StrEnum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated, Any, NoReturn

import typer
from margin_core import (
    AgentLoadError,
    AgentNotFoundError,
    AgentRegistry,
    AgentResult,
    BaseAgent,
    InputValidationError,
    RunContext,
    default_registry,
)
from margin_core.config import get_settings
from margin_core.inputs import bind_input
from margin_core.logging import LOGGER_NAME, configure_logging
from margin_core.reporting import to_json, to_markdown
from rich.console import Console

from margin_cli import __version__
from margin_cli.execution import (
    ExplicitLLMError,
    ProgressDisplay,
    TerminalQuestions,
    execute_cancellable,
    make_llm,
)
from margin_cli.render import agents_table, fields_table, input_fields


class ExitCode(IntEnum):
    OK = 0
    RESULT_ERROR = 1
    USAGE = 2
    AGENT_UNAVAILABLE = 3
    PARTIAL = 4
    CANCELLED = 130


class ReportFormat(StrEnum):
    markdown = "markdown"
    json = "json"


app = typer.Typer(
    name="margin",
    help="List, inspect and run the agents installed with margin.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)

stderr = Console(stderr=True)


def get_registry() -> AgentRegistry:
    """The registry used by every command (tests replace this)."""
    return default_registry()


def fail(message: str, code: ExitCode) -> NoReturn:
    stderr.print(f"[bold red]Error:[/] {message}", highlight=False, markup=True)
    raise typer.Exit(int(code))


def load_agent_class(registry: AgentRegistry, agent_id: str) -> type[BaseAgent]:
    try:
        return registry.get_agent_class(agent_id)
    except (AgentNotFoundError, AgentLoadError) as exc:
        fail(str(exc), ExitCode.AGENT_UNAVAILABLE)


@app.callback()
def main(
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show debug logs on stderr.")
    ] = False,
) -> None:
    """List, inspect and run the agents installed with margin."""
    library_logger = logging.getLogger(LOGGER_NAME)
    if verbose:
        configure_logging("DEBUG")
        library_logger.propagate = False
    elif not library_logger.handlers:
        # Problems reach the user through the report, not as raw log lines.
        library_logger.addHandler(logging.NullHandler())
        library_logger.propagate = False


@app.command("version")
def show_version() -> None:
    """Show the versions of the CLI and the core library."""
    try:
        core = version("margin-core")
    except PackageNotFoundError:
        core = "unknown"
    typer.echo(f"margin-cli v{__version__} (core v{core})")


@app.command("list")
def list_agents(
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON instead of a table.")] = False,
) -> None:
    """List installed agents."""
    registry = get_registry()
    infos = registry.list_agents()
    errors = registry.load_errors
    if as_json:
        payload = {
            "agents": [
                {k: v for k, v in info.model_dump().items() if not k.endswith("_schema")}
                for info in infos
            ],
            "load_errors": errors,
        }
        typer.echo(json.dumps(payload, indent=2))
    elif infos:
        Console().print(agents_table(infos))
    else:
        stderr.print("No agents are installed.")
    for name, error in errors.items():
        stderr.print(f"[yellow]Could not load {name}:[/] {error}", highlight=False)


@app.command("info")
def agent_info(
    agent_id: Annotated[str, typer.Argument(help="Agent id, as shown by 'margin list'.")],
    as_json: Annotated[
        bool, typer.Option("--json", help="Print the full description and schemas as JSON.")
    ] = False,
) -> None:
    """Describe an agent and its input fields."""
    info = load_agent_class(get_registry(), agent_id).info()
    if as_json:
        typer.echo(info.model_dump_json(indent=2))
        return
    console = Console()
    console.print(f"[bold]{info.name}[/] ([cyan]{info.id}[/]) v{info.version}", highlight=False)
    console.print(info.description, highlight=False)
    console.print()
    console.print(fields_table(info))
    primary = next((r for r in input_fields(info) if r["primary"]), None)
    example = f"margin run {info.id}" + (f" <{primary['name']}>" if primary else "")
    console.print(f"\nUsage: {example} [--set field=value ...]", highlight=False)


def _read_input_file(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        fail(f"Cannot read {path}: {exc.strerror}", ExitCode.USAGE)
    except json.JSONDecodeError as exc:
        fail(f"{path} is not valid JSON: {exc}", ExitCode.USAGE)
    if not isinstance(data, dict):
        fail(f"{path} must contain a JSON object", ExitCode.USAGE)
    return data


def _render(result: AgentResult, fmt: ReportFormat) -> str:
    return to_json(result) + "\n" if fmt is ReportFormat.json else to_markdown(result)


def _exit_code(result: AgentResult | None, cancelled: bool, strict: bool) -> ExitCode:
    if cancelled or result is None:
        return ExitCode.CANCELLED
    if result.status == "error":
        return ExitCode.RESULT_ERROR
    if result.status == "partial" and strict:
        return ExitCode.PARTIAL
    return ExitCode.OK


@app.command("run")
def run_agent(
    agent_id: Annotated[str, typer.Argument(help="Agent id, as shown by 'margin list'.")],
    primary: Annotated[
        str | None,
        typer.Argument(metavar="[INPUT]", help="Value for the agent's main input field."),
    ] = None,
    assignments: Annotated[
        list[str] | None,
        typer.Option("--set", "-s", metavar="FIELD=VALUE", help="Set an input field (repeatable)."),
    ] = None,
    input_file: Annotated[
        Path | None, typer.Option("--input", "-i", help="JSON file with input fields.")
    ] = None,
    fmt: Annotated[
        ReportFormat | None,
        typer.Option("--format", "-f", help="Report format [default: from --out, else markdown]."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option("--out", "-o", help="Write the report to a file.")
    ] = None,
    provider: Annotated[
        str | None, typer.Option(help="LLM provider: local, anthropic, openai or mock.")
    ] = None,
    model: Annotated[str | None, typer.Option(help="LLM model name.")] = None,
    max_cost: Annotated[
        float | None, typer.Option(help="Maximum LLM spend for this run, in USD.", min=0)
    ] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="No progress display.")] = False,
    strict: Annotated[
        bool, typer.Option(help="Exit with code 4 when the result is only partial.")
    ] = False,
) -> None:
    """Run an agent and print its report."""
    agent_cls = load_agent_class(get_registry(), agent_id)
    base = _read_input_file(input_file)
    try:
        raw = bind_input(agent_cls, positional=primary, assignments=assignments or [], base=base)
        parsed = agent_cls.parse_input(raw)
    except InputValidationError as exc:
        fail(str(exc), ExitCode.USAGE)

    if fmt is None:
        fmt = (
            ReportFormat.json
            if out is not None and out.suffix == ".json"
            else ReportFormat.markdown
        )

    settings = get_settings()
    budget = max_cost if max_cost is not None else settings.max_cost_usd
    try:
        llm = make_llm(provider, model, budget, settings)
    except ExplicitLLMError as exc:
        fail(str(exc), ExitCode.USAGE)

    agent = agent_cls(llm=llm)
    display = ProgressDisplay(stderr, agent_cls.name, enabled=not quiet)
    # Questions are asked only when someone is at the terminal; otherwise they take their
    # defaults, and the report marks those answers as not confirmed.
    interactive = sys.stdin is not None and sys.stdin.isatty() and stderr.is_terminal
    with display as on_progress:
        responder = TerminalQuestions(stderr, display) if interactive else None
        ctx = RunContext(progress=on_progress, max_cost_usd=budget, responder=responder)
        try:
            result = asyncio.run(execute_cancellable(agent, parsed, ctx))
        except KeyboardInterrupt:  # second Ctrl+C: stop immediately
            result = None
            ctx.cancel_token.cancel()

    cancelled = ctx.cancel_token.cancelled
    if result is not None and not cancelled:
        report = _render(result, fmt)
        if out is not None:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(report, encoding="utf-8")
            stderr.print(f"Report written to {out}", highlight=False)
        else:
            typer.echo(report, nl=False)
        for warning in result.warnings:
            stderr.print(f"[yellow]Warning:[/] {warning}", highlight=False)
        if result.status == "error":
            stderr.print(f"[bold red]Run failed:[/] {result.error}", highlight=False)
    else:
        stderr.print("[yellow]Cancelled.[/]")
    raise typer.Exit(int(_exit_code(result, cancelled, strict)))


if __name__ == "__main__":
    app()
