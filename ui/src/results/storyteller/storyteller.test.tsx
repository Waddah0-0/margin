import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { AgentResult, RunView } from "../../api/client";
import { StorytellerResult } from "./StorytellerResult";
import { formatValue } from "./types";

const fact = {
  id: "F009",
  kind: "period_change",
  title: "Sales: 2024-01 to 2024-03 against 2024-07 to 2024-09",
  statement: "Sales rose 10.9% from 118,060 in 2024-01 to 2024-03 to 130,916 in 2024-07 to 2024-09.",
  value: 0.109,
  format: "change",
  method: "The sum of sales in 2024-07 to 2024-09, compared with the start of the data.",
  n: 1472,
  confidence: "high",
  caveats: [],
  importance: 0.85,
  sql: "SELECT 1",
  checked: true,
};

const data = {
  source: { file: "sales.csv", format: "csv", table: "sales", tables: [{ name: "sales" }] },
  cleaning: {
    rows_in: 2400,
    rows_out: 2400,
    columns_in: 8,
    columns_out: 8,
    steps: [
      {
        id: "dates:order_date",
        kind: "dates",
        column: "order_date",
        summary: "Read 2,400 values as dates (day first)",
        decided_by: "user",
        examples: [{ row: 2, before: "31/01/2024", after: "2024-01-31" }],
        unreadable: [],
        rows_removed: 0,
        cells_emptied: 0,
      },
    ],
    check: ["2,400 rows in, 0 removed by the steps above, 2,400 out"],
  },
  columns: [
    {
      name: "sales",
      type: "number",
      role: "measure",
      aggregation: "sum",
      reason: "its name says it adds up",
      count: 2400,
      missing: 0,
      distinct: 2300,
      personal: false,
      notes: [],
    },
  ],
  setup: { north_star: "sales", grain: "one order (order_id)" },
  facts: { periods: [], partial: [], facts: [fact], check: [] },
  story: {
    title: "Sales grew, led by Technology",
    shape: "performance",
    written_by: "model",
    model: "qwen3.5:9b",
    attempts: 2,
    rejected: ["Draft 1: a number was typed in"],
    pages: [
      {
        id: "pulse",
        role: "pulse",
        title: "Sales rose over the period",
        headline: {
          text: "Sales rose 10.9% over the period.",
          fact_ids: ["F009"],
          parts: [{ text: "Sales rose " }, { text: "10.9%", fact_id: "F009" }, { text: " over the period." }],
        },
        body: [],
        actions: [],
        charts: [
          {
            kind: "bars",
            title: "Sales by category",
            fact_id: "F009",
            format: "number",
            points: [
              { label: "Technology", value: 222141, highlight: true },
              { label: "Furniture", value: 120000 },
            ],
          },
        ],
        fact_ids: ["F009"],
      },
      {
        id: "actions",
        role: "actions",
        title: "What to check next",
        headline: { text: "These are hypotheses to test, not conclusions.", fact_ids: [] },
        body: [],
        actions: [{ text: "Find out what happened in 2024-08.", check: "Read the records.", fact_ids: [] }],
        fact_ids: [],
      },
    ],
  },
  files: [],
};

const result: AgentResult = {
  agent_id: "data-storyteller",
  agent_version: "0.1.0",
  status: "ok",
  summary: "Sales grew.",
  findings: [],
  warnings: [],
  data,
  error: null,
  metadata: {
    duration_s: 2,
    model: "qwen3.5:9b",
    usage: { llm_calls: 2, input_tokens: 10, output_tokens: 10, cost_usd: 0 },
    started_at: null,
    finished_at: null,
    extra: {},
  },
};

const run: RunView = {
  run_id: "0123456789abcdef",
  agent_id: "data-storyteller",
  status: "done",
  queue_position: null,
  last_event: 0,
  progress: null,
  created_at: "2026-10-27T10:00:00Z",
  started_at: "2026-10-27T10:00:00Z",
  finished_at: "2026-10-27T10:00:02Z",
  result,
};

describe("StorytellerResult", () => {
  it("tells the story page by page, with who wrote it", () => {
    render(<StorytellerResult run={run} result={result} />);
    expect(screen.getByRole("heading", { level: 1, name: "Sales grew, led by Technology" })).toBeTruthy();
    expect(screen.getByText("Written by qwen3.5:9b in 2 drafts")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Sales rose over the period" })).toBeTruthy();
    expect(screen.getByText("Find out what happened in 2024-08.")).toBeTruthy();
    expect(screen.getByText("Draft 1: a number was typed in")).toBeTruthy();
  });

  it("opens the fact behind a number", async () => {
    const user = userEvent.setup();
    render(<StorytellerResult run={run} result={result} />);
    await user.click(screen.getByRole("button", { name: "10.9%" }));
    const panel = screen.getByRole("complementary", { name: "Fact F009" });
    expect(within(panel).getByText(/compared with the start of the data/)).toBeTruthy();
    expect(within(panel).getByText(/Recomputed in DuckDB/)).toBeTruthy();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("complementary", { name: "Fact F009" })).toBeNull();
  });

  it("keeps the punctuation touching a number on the same line as it", () => {
    const parts = [{ text: "Sales rose (" }, { text: "10.9%", fact_id: "F009" }, { text: "), then fell." }];
    const page = { ...data.story.pages[0], headline: { text: "", fact_ids: ["F009"], parts }, charts: [] };
    const story = { ...data.story, pages: [page] };
    render(<StorytellerResult run={run} result={{ ...result, data: { ...data, story } }} />);
    const together = screen.getByRole("button", { name: "10.9%" }).parentElement as HTMLElement;
    expect(together.textContent).toBe("(10.9%),");
    expect(together.parentElement?.textContent).toBe("Sales rose (10.9%), then fell.");
  });

  it("shows any chart as a table", async () => {
    const user = userEvent.setup();
    render(<StorytellerResult run={run} result={result} />);
    expect(screen.getByRole("img", { name: "Sales by category, as bars" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Show as a table" }));
    const table = screen.getAllByRole("table")[0] as HTMLElement;
    expect(within(table).getByRole("rowheader", { name: "Technology" })).toBeTruthy();
    expect(within(table).getByText("222,141")).toBeTruthy();
  });

  it("falls back to the generic viewer for a run without a story", () => {
    const clean = { ...result, summary: "Cleaned sales.csv.", data: { ...data, story: null } };
    render(<StorytellerResult run={run} result={clean} />);
    expect(screen.getByText("Cleaned sales.csv.")).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
  });
});

describe("formatValue", () => {
  it("writes numbers the way the facts engine does", () => {
    expect(formatValue(0.109, "change")).toBe("+10.9%");
    expect(formatValue(0.2, "percent")).toBe("20%");
    expect(formatValue(2.8, "ratio")).toBe("2.8 times");
    expect(formatValue(4300000, "number")).toBe("4.30M");
    expect(formatValue(406594, "number")).toBe("406,594");
    expect(formatValue(161.03, "number", "$")).toBe("$161.03");
  });
});
