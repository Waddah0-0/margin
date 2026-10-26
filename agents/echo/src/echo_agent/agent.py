"""Echo agent: the smallest complete example of the agent contract."""

from __future__ import annotations

from margin_core import AgentResult, BaseAgent, Choice, Evidence, Finding, Question, RunContext

from echo_agent.models import EchoInput, EchoOutput

STYLE = Question(
    id="style",
    prompt="How should the message be echoed?",
    choices=[
        Choice(value="as_typed", label="As typed"),
        Choice(value="capitals", label="In capitals"),
    ],
    default="as_typed",
)


class EchoAgent(BaseAgent):
    id = "echo"
    name = "Echo Agent"
    description = "Echoes its input back. Useful for smoke-testing the toolchain."
    version = "0.1.0"
    InputModel = EchoInput
    OutputModel = EchoOutput
    primary_input = "message"

    async def run(self, input: EchoInput, ctx: RunContext) -> AgentResult:
        message = input.message
        if input.ask:
            question = STYLE.model_copy(
                update={"evidence": [Evidence(kind="input", detail=f"message: {message}")]}
            )
            answers = await ctx.ask(
                [question],
                title="Before echoing",
                preset=input.answers,
                assume_defaults=input.assume_defaults,
            )
            if answers["style"].value == "capitals":
                message = message.upper()

        ctx.report_progress("echo", "Echoing message", 0.0)
        echoed = " ".join([message] * input.repeat)

        llm_reply: str | None = None
        if input.use_llm:
            ctx.check_cancelled()
            ctx.report_progress("llm", "Asking the LLM", 0.5)
            llm_reply = (await ctx.require_llm().complete(input.message)).text

        ctx.report_progress("done", "Finished", 1.0)
        return self.make_result(
            summary=f"Echoed {len(echoed)} characters ({input.repeat}x).",
            output=EchoOutput(echoed=echoed, length=len(echoed), llm_reply=llm_reply),
            findings=[
                Finding(
                    title="Echo",
                    summary=echoed,
                    evidence=[Evidence(kind="metric", detail=f"length={len(echoed)}")],
                )
            ],
        )
