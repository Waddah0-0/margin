"""The Secret Leaks agent."""

from __future__ import annotations

from margin_core import AgentResult, BaseAgent, RunContext

from secret_leaks.models import SecretLeaksInput, SecretLeaksOutput


class SecretLeaksAgent(BaseAgent):
    id = "secret-leaks"
    name = "Secret Leaks"
    description = (
        "Scans workspace files and git history for hardcoded secrets, API keys, private keys, "
        "and database credentials, reporting only redacted previews."
    )
    version = "0.1.0"
    InputModel = SecretLeaksInput
    OutputModel = SecretLeaksOutput
    primary_input = "target"
    uses_llm = False
    requires_git = True

    async def run(self, input: SecretLeaksInput, ctx: RunContext) -> AgentResult:
        from secret_leaks.scanner import SCAN_FILTERS, scan_workspace

        async with await ctx.load_workspace(
            input.target, paths=input.paths, branch=input.branch, filters=SCAN_FILTERS
        ) as ws:
            outcome = await scan_workspace(ws, input, ctx)
        ctx.report_progress("done", "Finished", 1.0)
        return self.make_result(
            summary=outcome.summary,
            output=outcome.output,
            findings=outcome.findings,
            status="partial" if outcome.partial else "ok",
        )
