import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AgentResult, RunView } from "../api/client";
import { GenericResult } from "./GenericResult";
import { type ResultViewProps, registerResultView, resultViewFor } from "./registry";

const result: AgentResult = {
  agent_id: "echo",
  agent_version: "0.1.0",
  status: "partial",
  summary: "Echoed 5 characters",
  findings: [
    {
      title: "Echo",
      summary: "hello",
      severity_or_score: 0.4,
      evidence: [{ kind: "metric", location: "a.py:3", detail: "length=5", weight: 0.5 }],
    },
  ],
  warnings: ["The model was not available"],
  data: { echoed: "hello" },
  error: null,
  metadata: {
    duration_s: 0.25,
    model: null,
    usage: { llm_calls: 0, input_tokens: 0, output_tokens: 0, cost_usd: 0 },
    started_at: null,
    finished_at: null,
    extra: {},
  },
};

const run: RunView = {
  run_id: "0123456789abcdef",
  agent_id: "echo",
  status: "done",
  queue_position: null,
  last_event: 0,
  progress: null,
  created_at: "2026-10-19T10:00:00Z",
  started_at: "2026-10-19T10:00:00Z",
  finished_at: "2026-10-19T10:00:01Z",
  result,
};

describe("result views", () => {
  it("fall back to the generic viewer", () => {
    expect(resultViewFor("no-such-agent")).toBe(GenericResult);
  });

  it("use a registered custom view", () => {
    const Custom = ({ result }: ResultViewProps) => <p>custom {result.summary}</p>;
    registerResultView("custom-agent", Custom);
    expect(resultViewFor("custom-agent")).toBe(Custom);
  });

  it("generic viewer shows summary, findings, evidence, warnings and status", () => {
    render(<GenericResult run={run} result={result} />);
    expect(screen.getByText("Echoed 5 characters")).toBeTruthy();
    expect(screen.getByText("Partial result")).toBeTruthy();
    expect(screen.getByText("Echo")).toBeTruthy();
    expect(screen.getByText("a.py:3")).toBeTruthy();
    expect(screen.getByText("+0.50")).toBeTruthy();
    expect(screen.getByText("The model was not available")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Markdown" })).toBeTruthy();
  });
});
