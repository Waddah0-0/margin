import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { AgentResult, RunView } from "../../api/client";
import { resultViewFor } from "../registry";
import { DetectorResult } from "./DetectorResult";
import { buildTree, collectEvidence, fileScore, type TreeFolder } from "./logic";
import { asDetectorData, type DetectorData } from "./types";

const verdict = {
  likelihood_ai: 0.8,
  confidence: 0.7,
  evidence_for: [
    { line_start: 3, line_end: 3, quote: "# add the numbers", why: "comment restates the code" },
  ],
  evidence_against: [{ line_start: 5, line_end: 5, quote: "x = hack()", why: "odd shortcut" }],
  uncertainty_notes: "short file",
};

const data = {
  methodology_version: "detector-0.2.0+methodology-v1",
  estimate: 0.71,
  estimate_range: [0.4, 0.9],
  confidence: "low",
  confidence_reasons: ["only 2 files could be analysed"],
  metadata_markers: [
    { kind: "commit_trailer", tool: "Claude", location: "abc1234567", detail: "1 of 2 commits" },
  ],
  repo_signals: [],
  files: [
    {
      path: "src/a.py",
      language: "python",
      lines: 40,
      is_test: false,
      probability: 0.55,
      signals: [],
      judge: verdict,
      ai_commit_touches: 1,
    },
    {
      path: "src/b.py",
      language: "python",
      lines: 30,
      is_test: false,
      probability: 0.6,
      signals: [],
      judge: null,
      ai_commit_touches: 0,
    },
  ],
  files_analyzed: 2,
  files_skipped: 2,
  languages: { python: 2 },
  unsupported_languages: { go: 1 },
  excerpts: [
    {
      path: "src/a.py",
      hunks: [
        { start_line: 1, lines: ["import os", "", "# add the numbers", "def add(a, b):", "x = hack()"] },
      ],
      marks: [
        { line_start: 3, line_end: 3, side: "for", source: "judge", note: "comment restates the code" },
        { line_start: 5, line_end: 5, side: "against", source: "judge", note: "odd shortcut" },
      ],
      truncated: false,
    },
  ],
  commits: [
    {
      sha: "abc1234567",
      date: "2026-02-01T10:00:00Z",
      subject: "Add a",
      files_changed: 20,
      merge: false,
      tools: ["Claude"],
      large: true,
    },
    {
      sha: "def7654321",
      date: "2026-01-01T10:00:00Z",
      subject: "Start",
      files_changed: 1,
      merge: false,
      tools: [],
      large: false,
    },
  ],
  commits_total: 2,
  unscored_files: [
    { path: "main.go", reason: "unsupported_language" },
    { path: "node_modules/", reason: "ignored_dir" },
  ],
  unscored_truncated: false,
} satisfies Record<string, unknown>;

const findings = [
  { title: "Estimated likelihood of AI assistance", summary: "0.71", evidence: [] },
  {
    title: "Evidence toward human authorship",
    summary: "",
    evidence: [{ kind: "file", location: "src/b.py:2", detail: "hand-tuned constant", weight: -0.2 }],
  },
  { title: "Coverage", summary: "Only 70% of the code is in a supported language." },
];

const result: AgentResult = {
  agent_id: "ai-code-detector",
  agent_version: "0.2.0",
  status: "ok",
  summary: "Estimated likelihood 0.71",
  findings,
  warnings: [],
  data,
  error: null,
  metadata: {
    duration_s: 2,
    model: "qwen3.5:9b",
    usage: { llm_calls: 1, input_tokens: 1, output_tokens: 1, cost_usd: 0 },
    started_at: null,
    finished_at: null,
    extra: {},
  },
};

const run: RunView = {
  run_id: "0123456789abcdef",
  agent_id: "ai-code-detector",
  status: "done",
  queue_position: null,
  last_event: 0,
  progress: null,
  created_at: "2026-10-19T10:00:00Z",
  started_at: "2026-10-19T10:00:00Z",
  finished_at: "2026-10-19T10:00:02Z",
  result,
};

const parsed = asDetectorData(data) as DetectorData;

describe("detector data", () => {
  it("accepts detector output and rejects anything else", () => {
    expect(parsed.estimate).toBe(0.71);
    expect(asDetectorData({ estimate: 0.5 })).toBeNull();
    expect(asDetectorData(null)).toBeNull();
    // results from before excerpts existed still parse, with empty lists
    const { excerpts: _e, commits: _c, ...older } = data;
    expect(asDetectorData(older)?.excerpts).toEqual([]);
  });

  it("scores a file by the model's verdict when there is one", () => {
    expect(fileScore(parsed.files[0] as DetectorData["files"][number])).toEqual({
      value: 0.8,
      byModel: true,
    });
    expect(fileScore(parsed.files[1] as DetectorData["files"][number])).toEqual({
      value: 0.6,
      byModel: false,
    });
  });

  it("builds a folder tree, with unscored files and skipped folders on request", () => {
    const tree = buildTree(parsed);
    expect(tree.children.map((c) => c.name)).toEqual(["src"]);
    const src = tree.children[0] as TreeFolder;
    expect(src.children.map((c) => c.name)).toEqual(["a.py", "b.py"]);
    expect(src.scored).toBe(2);

    const all = buildTree(parsed, { includeUnscored: true });
    expect(all.children.map((c) => c.name)).toEqual(["src", "main.go", "node_modules/"]);
    expect(buildTree(parsed, { query: "B.PY" }).children.length).toBe(1);
  });

  it("collects the model's quotes and the ranked signals into two columns", () => {
    const columns = collectEvidence(parsed, findings);
    expect(columns.for.map((e) => [e.source, e.location])).toEqual([["judge", "src/a.py:3"]]);
    expect(columns.against.map((e) => [e.source, e.location, e.line])).toEqual([
      ["judge", "src/a.py:5", 5],
      ["signal", "src/b.py:2", 2],
    ]);
  });
});

describe("DetectorResult", () => {
  it("is the registered view for the detector", () => {
    expect(resultViewFor("ai-code-detector")).toBe(DetectorResult);
  });

  it("shows the estimate, markers, evidence, marked code and history", async () => {
    render(<DetectorResult run={run} result={result} />);
    expect(screen.getByText("0.71")).toBeTruthy();
    expect(screen.getByText(/Low confidence/)).toBeTruthy();
    expect(screen.getByText(/metadata names AI tools: Claude/)).toBeTruthy();
    expect(screen.getByText(/estimate, not proof/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: /Toward AI/ })).toBeTruthy();

    // the most likely file with code opens first, with its marked lines and notes
    const code = screen.getByRole("table");
    expect(within(code).getByText("# add the numbers").closest("tr")?.getAttribute("data-side")).toBe("for");
    expect(within(code).getByText("x = hack()").closest("tr")?.getAttribute("data-side")).toBe("against");
    expect(screen.getByText("the model's verdict")).toBeTruthy();

    // picking signal evidence in another file opens that file
    await userEvent.setup().click(screen.getByRole("button", { name: /hand-tuned constant/i }));
    expect(screen.getAllByText("src/b.py").length).toBeGreaterThan(0);
    expect(screen.getByText(/No code excerpt/)).toBeTruthy();

    expect(screen.getByText("Add a")).toBeTruthy(); // notable commit
    expect(screen.getByText("Coverage")).toBeTruthy(); // other findings still shown
  });

  it("falls back to the generic viewer when the data is not the detector's", () => {
    render(<DetectorResult run={run} result={{ ...result, data: { something: "else" } }} />);
    expect(screen.getByText("Summary")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: /Toward AI/ })).toBeNull();
  });
});
