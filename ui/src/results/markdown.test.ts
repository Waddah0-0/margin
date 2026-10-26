import { describe, expect, it } from "vitest";
import type { AgentResult } from "../api/client";
import { toMarkdown } from "./markdown";

const result: AgentResult = {
  agent_id: "echo",
  agent_version: "0.1.0",
  status: "partial",
  summary: "Echoed hello",
  findings: [
    {
      title: "Echo",
      summary: "hello",
      severity_or_score: 0.5,
      evidence: [{ kind: "file", location: "a.py:1", detail: "x | y", weight: -0.25 }],
    },
  ],
  warnings: ["LLM skipped"],
  data: {},
  error: null,
  metadata: {
    duration_s: 1.234,
    model: "qwen3.5:9b",
    usage: { llm_calls: 2, input_tokens: 10, output_tokens: 5, cost_usd: 0 },
    started_at: "2026-10-19T10:00:00.123456Z",
    finished_at: null,
    extra: {},
  },
};

describe("toMarkdown", () => {
  it("renders the same sections as the Python report", () => {
    const md = toMarkdown(result);
    expect(md).toContain("# echo report\n\n**Status:** partial  \n**Agent version:** 0.1.0");
    expect(md).toContain(
      "### Echo (0.50)\n\nhello\n\n**Evidence**\n\n- **file** `a.py:1` - x | y _(weight -0.25)_",
    );
    expect(md).toContain("## Warnings\n\n- LLM skipped");
    expect(md).toContain("| Duration | 1.23s |");
    expect(md).toContain("| Tokens (in/out) | 10/5 |");
    expect(md).toContain("| Started | 2026-10-19T10:00:00Z |");
    expect(md).not.toContain("## Answers");
    expect(md.endsWith("\n")).toBe(true);
  });

  it("lists the answers and who gave them", () => {
    const asked: AgentResult = {
      ...result,
      metadata: {
        ...result.metadata,
        answers: [
          { question_id: "a", prompt: "Date format?", value: "dmy", label: "DD/MM", source: "user" },
          { question_id: "b", prompt: "Grain?", value: "order", label: "An order", source: "default" },
        ],
      },
    };
    const md = toMarkdown(asked);
    expect(md).toContain("## Answers\n\n| Question | Answer | Given by |\n|---|---|---|");
    expect(md).toContain("| Date format? | DD/MM | you |");
    expect(md).toContain("| Grain? | An order | default, not confirmed |");
  });
});
