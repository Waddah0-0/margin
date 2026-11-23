"""Input and output models for the Secret Leaks agent."""

from __future__ import annotations

import re
from typing import Literal

from margin_core import AgentInput
from pydantic import BaseModel, Field, field_validator

Severity = Literal["low", "medium", "high"]
FindingSource = Literal["workspace", "git_history"]


class SecretLeaksInput(AgentInput):
    """Input configuration for scanning a target for leaked secrets."""

    target: str = Field(
        min_length=1,
        description="Local directory/file path or public GitHub repository URL.",
        examples=["."],
    )
    scan_git_history: bool = Field(
        default=True,
        description="Scan recent git commit patches for introduced or deleted secrets.",
    )
    history_depth: int = Field(
        default=50,
        ge=1,
        le=5000,
        description="Maximum number of commits to inspect when scanning git history.",
    )
    paths: list[str] | None = Field(
        default=None,
        description="Restrict scanning to these relative files or directories.",
    )
    branch: str | None = Field(
        default=None,
        description="Branch to scan (GitHub URL targets only).",
    )
    min_severity: Severity = Field(
        default="low",
        description="Minimum severity level to report ('low', 'medium', or 'high').",
    )
    allowlist_patterns: list[str] = Field(
        default_factory=list,
        description="Regular expressions matching values or lines to suppress.",
    )

    @field_validator("allowlist_patterns")
    @classmethod
    def _validate_allowlist_patterns(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            if not pattern:
                raise ValueError("allowlist_patterns entries must be non-empty")
            try:
                re.compile(pattern)
            except re.error as exc:
                raise ValueError(f"Invalid allowlist regex {pattern!r}: {exc}") from exc
        return patterns


class SecretMatchSummary(BaseModel):
    """Redacted summary of one potential secret match (never contains raw secret text)."""

    rule_id: str
    rule_name: str
    severity: Severity
    source: FindingSource
    file_path: str
    line: int | None = None
    commit_sha: str | None = None
    in_head: bool | None = None
    redacted_preview: str
    entropy: float | None = None


class SecretLeaksOutput(BaseModel):
    """Structured scan summary returned in ``AgentResult.data``."""

    target: str
    total_matches: int
    counts_by_severity: dict[Severity, int]
    workspace_matches: int
    git_history_matches: int
    files_scanned: int
    commits_scanned: int
    rules_triggered: list[str]
    matches: list[SecretMatchSummary]
