"""Core foundation library for margin.

Public API::

    from margin_core import BaseAgent, RunContext, AgentResult, Finding, Evidence
    from margin_core import run_agent, list_agents, get_agent
"""

from margin_core.agent import (
    BaseAgent,
    CancellationToken,
    ProgressCallback,
    Responder,
    RunContext,
)
from margin_core.errors import (
    AgentLoadError,
    AgentNotFoundError,
    AgentsLibError,
    BudgetExceededError,
    InputValidationError,
    InvalidTargetError,
    LimitExceededError,
    LLMError,
    LoaderError,
    NoAnswerError,
    RunCancelledError,
    TransientLLMError,
)
from margin_core.models import (
    AgentInfo,
    AgentInput,
    AgentResult,
    Answer,
    AnswersInput,
    Choice,
    Evidence,
    Finding,
    ProgressEvent,
    Question,
    QuestionBatch,
    RunMetadata,
    TokenUsage,
)
from margin_core.registry import AgentRegistry, default_registry, get_agent, list_agents
from margin_core.runner import run_agent

__version__ = "0.1.1"

__all__ = [
    "AgentInfo",
    "AgentInput",
    "AgentLoadError",
    "AgentNotFoundError",
    "AgentRegistry",
    "AgentResult",
    "AgentsLibError",
    "Answer",
    "AnswersInput",
    "BaseAgent",
    "BudgetExceededError",
    "CancellationToken",
    "Choice",
    "Evidence",
    "Finding",
    "InputValidationError",
    "InvalidTargetError",
    "LLMError",
    "LimitExceededError",
    "LoaderError",
    "NoAnswerError",
    "ProgressCallback",
    "ProgressEvent",
    "Question",
    "QuestionBatch",
    "Responder",
    "RunCancelledError",
    "RunContext",
    "RunMetadata",
    "TokenUsage",
    "TransientLLMError",
    "__version__",
    "default_registry",
    "get_agent",
    "list_agents",
    "run_agent",
]
