"""Render an :class:`AgentResult` as Markdown (works for any agent)."""

from __future__ import annotations

from pathlib import Path

from margin_core.models import AgentResult, Evidence

_STATUS_LABEL = {"ok": "ok", "partial": "partial", "error": "error"}
_ANSWERED_BY = {"user": "you", "preset": "the run's input", "default": "default, not confirmed"}


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _evidence_line(ev: Evidence) -> str:
    parts = [f"**{ev.kind}**"]
    if ev.location:
        parts.append(f"`{ev.location}`")
    line = " ".join(parts) + f" - {ev.detail}"
    if ev.weight is not None:
        line += f" _(weight {ev.weight:+.2f})_"
    return f"- {line}"


def to_markdown(result: AgentResult) -> str:
    md: list[str] = [
        f"# {result.agent_id} report",
        "",
        f"**Status:** {_STATUS_LABEL.get(result.status, result.status)}  ",
        f"**Agent version:** {result.agent_version}",
        "",
        "## Summary",
        "",
        result.summary,
        "",
    ]
    if result.error:
        md += ["## Error", "", "```", result.error, "```", ""]

    if result.findings:
        md += ["## Findings", ""]
        for finding in result.findings:
            title = finding.title
            if finding.severity_or_score is not None:
                title += f" ({finding.severity_or_score:.2f})"
            md += [f"### {title}", "", finding.summary, ""]
            if finding.evidence:
                md += ["**Evidence**", ""]
                md += [_evidence_line(ev) for ev in finding.evidence]
                md.append("")

    if result.warnings:
        md += ["## Warnings", ""]
        md += [f"- {w}" for w in result.warnings]
        md.append("")

    meta = result.metadata
    if meta.answers:
        md += ["## Answers", "", "| Question | Answer | Given by |", "|---|---|---|"]
        md += [
            f"| {_cell(a.prompt)} | {_cell(a.label)} | {_ANSWERED_BY.get(a.source, a.source)} |"
            for a in meta.answers
        ]
        md.append("")

    rows: list[tuple[str, object]] = []
    if meta.duration_s is not None:
        rows.append(("Duration", f"{meta.duration_s:.2f}s"))
    if meta.model:
        rows.append(("Model", meta.model))
    if meta.usage.llm_calls:
        rows += [
            ("LLM calls", meta.usage.llm_calls),
            ("Tokens (in/out)", f"{meta.usage.input_tokens}/{meta.usage.output_tokens}"),
            ("Estimated cost", f"${meta.usage.cost_usd:.4f}"),
        ]
    if meta.started_at:
        rows.append(("Started", meta.started_at.isoformat(timespec="seconds")))
    if rows:
        md += ["## Run metadata", "", "| Field | Value |", "|---|---|"]
        md += [f"| {_cell(k)} | {_cell(v)} |" for k, v in rows]
        md.append("")

    return "\n".join(md).rstrip() + "\n"


def write_markdown(result: AgentResult, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(to_markdown(result), encoding="utf-8")
    return out
