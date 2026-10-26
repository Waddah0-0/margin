"""Input and output models of the echo agent."""

from __future__ import annotations

from margin_core import AnswersInput
from pydantic import BaseModel, Field


class EchoInput(AnswersInput):
    message: str = Field(min_length=1, description="Text to echo back.", examples=["Hello"])
    repeat: int = Field(default=1, ge=1, le=10, description="How many times to repeat it.")
    use_llm: bool = Field(default=False, description="Also send the message to the LLM.")
    ask: bool = Field(
        default=False, description="Ask how to echo it first (an example of a question)."
    )


class EchoOutput(BaseModel):
    echoed: str
    length: int
    llm_reply: str | None = None
