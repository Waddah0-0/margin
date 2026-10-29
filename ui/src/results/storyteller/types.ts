/**
 * The Data Storyteller's `data` (its DataStorytellerOutput model), as its view uses it.
 * Results arrive as untyped JSON, so `asStorytellerData` checks the shape first; anything
 * unexpected falls back to the generic viewer.
 */

export type Format = "number" | "percent" | "change" | "count" | "ratio";

export interface TextPart {
  text: string;
  fact_id?: string | null;
}

export interface StorySentence {
  text: string;
  fact_ids: string[];
  parts?: TextPart[];
}

export interface StoryAction {
  text: string;
  check: string;
  fact_ids: string[];
}

export interface ChartPoint {
  label: string;
  value: number;
  before?: number | null;
  highlight?: boolean;
}

export interface Chart {
  kind: "line" | "bars" | "dumbbell" | "meter";
  title: string;
  fact_id: string;
  format: Format;
  unit?: string | null;
  points: ChartPoint[];
  before_label?: string | null;
  after_label?: string | null;
  note?: string | null;
}

export interface StoryPage {
  id: string;
  role: "pulse" | "drivers" | "nuance" | "actions";
  title: string;
  headline: StorySentence;
  body: StorySentence[];
  actions: StoryAction[];
  charts?: Chart[];
  fact_ids: string[];
}

export interface Story {
  title: string;
  shape: string;
  pages: StoryPage[];
  written_by: "model" | "template";
  model?: string | null;
  attempts: number;
  rejected: string[];
  context?: string | null;
}

export interface Fact {
  id: string;
  kind: string;
  title: string;
  statement: string;
  value: number;
  format: Format;
  unit?: string | null;
  method: string;
  n: number;
  confidence: "high" | "medium" | "low";
  caveats: string[];
  importance: number;
  sql?: string | null;
  points_sql?: string | null;
  checked: boolean;
}

export interface FactsReport {
  time?: string | null;
  periods: string[];
  partial: string[];
  facts: Fact[];
  check: string[];
}

export interface Change {
  row: number;
  before: string;
  after?: string | null;
}

export interface Step {
  id: string;
  kind: string;
  column?: string | null;
  summary: string;
  decided_by: "rule" | "user" | "preset" | "default";
  examples: Change[];
  unreadable: Change[];
  rows_removed: number;
  cells_emptied: number;
}

export interface ColumnProfile {
  name: string;
  type: "number" | "date" | "text" | "empty";
  role: string;
  aggregation: string;
  reason: string;
  unit?: string | null;
  count: number;
  missing: number;
  distinct: number;
  personal: boolean;
  notes: string[];
}

export interface StorytellerData {
  source: { file: string; format: string; table: string; tables: { name: string }[] };
  cleaning: {
    rows_in: number;
    rows_out: number;
    columns_in: number;
    columns_out: number;
    steps: Step[];
    check: string[];
  };
  columns: ColumnProfile[];
  setup?: { north_star?: string | null; grain: string } | null;
  facts?: FactsReport | null;
  story?: Story | null;
  files: string[];
}

export function asStorytellerData(data: unknown): StorytellerData | null {
  if (!data || typeof data !== "object") return null;
  const d = data as Partial<StorytellerData>;
  if (!d.source || !d.cleaning || !Array.isArray(d.columns)) return null;
  if (!Array.isArray(d.cleaning.steps)) return null;
  if (d.story && !Array.isArray(d.story.pages)) return null;
  return d as StorytellerData;
}

/** A number as the facts engine writes it (mirrors facts/base.py `fmt`). */
export function formatValue(value: number | null | undefined, format: Format, unit?: string | null): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "no value";
  const trim = (s: string) => s.replace(/\.0$/, "");
  if (format === "percent") return `${trim((value * 100).toFixed(1))}%`;
  if (format === "change") return `${value >= 0 ? "+" : ""}${trim((value * 100).toFixed(1))}%`;
  if (format === "ratio") return `${value.toFixed(1)} times`;
  if (format === "count") return Math.round(value).toLocaleString("en-US");
  const size = Math.abs(value);
  let text: string;
  if (size >= 1e9) text = `${(value / 1e9).toFixed(2)}B`;
  else if (size >= 1e6) text = `${(value / 1e6).toFixed(2)}M`;
  else if (size >= 1e4) text = Math.round(value).toLocaleString("en-US");
  else if (size >= 1) text = value.toLocaleString("en-US", { maximumFractionDigits: 2 });
  else text = Number(value.toPrecision(3)).toString();
  if (unit && unit !== "%") return unit.length === 1 ? `${unit}${text}` : `${text} ${unit}`;
  return text;
}

/** A compact axis tick: 1K, 12.5K, 1.2M. */
export function compact(value: number, format: Format): string {
  if (format === "percent") return `${Math.round(value * 100)}%`;
  const size = Math.abs(value);
  if (size >= 1e6) return `${Number((value / 1e6).toFixed(1))}M`;
  if (size >= 1e3) return `${Number((value / 1e3).toFixed(1))}K`;
  return `${Number(value.toFixed(2))}`;
}
