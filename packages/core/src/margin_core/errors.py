"""Exception hierarchy for margin.

Every error raised by ``margin_core`` derives from :class:`AgentsLibError`, so callers
(CLI, API) can catch one type and render a readable message.
"""


class AgentsLibError(Exception):
    """Base class for all margin errors."""


class AgentNotFoundError(AgentsLibError):
    """No agent is registered under the requested id."""


class AgentLoadError(AgentsLibError):
    """An agent entry point exists but could not be loaded."""


class InputValidationError(AgentsLibError):
    """The input does not match the agent's ``InputModel``."""


class RunCancelledError(AgentsLibError):
    """The run was cancelled through its cancellation token."""


class NoAnswerError(AgentsLibError):
    """An agent's question could not be answered: nobody to ask, or no answer in time."""


class LoaderError(AgentsLibError):
    """Base class for errors raised while loading a workspace."""


class InvalidTargetError(LoaderError):
    """The target (URL or path) is malformed, disallowed, or does not exist."""


class LimitExceededError(LoaderError):
    """A configured safety limit (size, file count, timeout) was exceeded."""


class LLMError(AgentsLibError):
    """Base class for LLM client errors."""


class TransientLLMError(LLMError):
    """A retryable LLM error (rate limit, 5xx, timeout, network)."""


class BudgetExceededError(LLMError):
    """The run's cost budget would be exceeded by another LLM call."""
