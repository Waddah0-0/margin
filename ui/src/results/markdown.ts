/** Render an AgentResult as Markdown. Mirrors margin_core.reporting.markdown_report. */
import type { AgentResult, Answer, Evidence } from "../api/client";

const ANSWERED_BY: Record<Answer["source"], string> = {
  user: "you",
  preset: "the run's input",
  default: "default, not confirmed",
};

const cell = (text: unknown) => String(text).replaceAll("|", "\\|").replaceAll("\n", " ");

const signed = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}`;

function evidenceLine(ev: Evidence): string {
  let line = `**${ev.kind}**`;
  if (ev.location) line += ` \`${ev.location}\``;
  line += ` - ${ev.detail}`;
  if (ev.weight !== null && ev.weight !== undefined) line += ` _(weight ${signed(ev.weight)})_`;
  return `- ${line}`;
}

export function toMarkdown(result: AgentResult): string {
  const md: string[] = [
    `# ${result.agent_id} report`,
    "",
    `**Status:** ${result.status}  `,
    `**Agent version:** ${result.agent_version}`,
    "",
    "## Summary",
    "",
    result.summary,
    "",
  ];
  if (result.error) md.push("## Error", "", "```", result.error, "```", "");

  const findings = result.findings ?? [];
  if (findings.length) {
    md.push("## Findings", "");
    for (const finding of findings) {
      let title = finding.title;
      if (finding.severity_or_score !== null && finding.severity_or_score !== undefined) {
        title += ` (${finding.severity_or_score.toFixed(2)})`;
      }
      md.push(`### ${title}`, "", finding.summary, "");
      const evidence = finding.evidence ?? [];
      if (evidence.length) {
        md.push("**Evidence**", "", ...evidence.map(evidenceLine), "");
      }
    }
  }

  const warnings = result.warnings ?? [];
  if (warnings.length) md.push("## Warnings", "", ...warnings.map((w) => `- ${w}`), "");

  const meta = result.metadata;
  const answers = meta?.answers ?? [];
  if (answers.length) {
    md.push("## Answers", "", "| Question | Answer | Given by |", "|---|---|---|");
    md.push(...answers.map((a) => `| ${cell(a.prompt)} | ${cell(a.label)} | ${ANSWERED_BY[a.source]} |`), "");
  }

  const rows: [string, unknown][] = [];
  if (meta) {
    if (meta.duration_s !== null && meta.duration_s !== undefined) {
      rows.push(["Duration", `${meta.duration_s.toFixed(2)}s`]);
    }
    if (meta.model) rows.push(["Model", meta.model]);
    const usage = meta.usage;
    if (usage?.llm_calls) {
      rows.push(
        ["LLM calls", usage.llm_calls],
        ["Tokens (in/out)", `${usage.input_tokens}/${usage.output_tokens}`],
        ["Estimated cost", `$${(usage.cost_usd ?? 0).toFixed(4)}`],
      );
    }
    if (meta.started_at) rows.push(["Started", meta.started_at.replace(/\.\d+/, "")]);
  }
  if (rows.length) {
    md.push("## Run metadata", "", "| Field | Value |", "|---|---|");
    md.push(...rows.map(([k, v]) => `| ${cell(k)} | ${cell(v)} |`), "");
  }
  return `${md.join("\n").trimEnd()}\n`;
}
