/**
 * The geometry of the tree and the sets of commits a reader can light up on it. Kept apart
 * from the components so it can be tested without a browser.
 */
import type { Commit, FileLife, HistoryData } from "./types";

export const ROW = 30;
export const CHAPTER_ROW = 46;
export const LANE = 14;
export const MAX_LANES = 16;
const PAD = 9;

/** Commits to light up on the tree, each with a word for what happened there. */
export interface Highlight {
  label: string;
  rows: Map<number, string>;
}

export interface Geometry {
  /** Top of each commit's row, in pixels from the top of the tree. */
  top: number[];
  /** Top of each chapter's heading row, by chapter index. */
  chapterTop: Map<number, number>;
  height: number;
  /** Width of the part the lanes are drawn in. */
  lanesWidth: number;
}

export function laneX(lane: number): number {
  return PAD + Math.min(lane, MAX_LANES - 1) * LANE;
}

/** Where every row sits. A chapter's heading row comes just above its newest commit. */
export function geometry(data: HistoryData): Geometry {
  const starts = new Map(data.chapters.map((c) => [c.first_row, c.index]));
  const top: number[] = [];
  const chapterTop = new Map<number, number>();
  let y = 0;
  data.commits.forEach((_, row) => {
    const chapter = starts.get(row);
    if (chapter !== undefined && data.chapters.length > 1) {
      chapterTop.set(chapter, y);
      y += CHAPTER_ROW;
    }
    top.push(y);
    y += ROW;
  });
  const lanes = Math.min(Math.max(data.repo.lanes, 1), MAX_LANES);
  return { top, chapterTop, height: y, lanesWidth: PAD * 2 + (lanes - 1) * LANE };
}

function n(value: number): string {
  return value.toFixed(1);
}

/**
 * The line from a commit down to one parent: into the lane the line runs in, straight down,
 * then into the parent. A parent that is not drawn takes the line to the bottom.
 */
export function edgePath(x1: number, y1: number, laneAt: number, x2: number, y2: number): string {
  const half = ROW / 2;
  if (y2 - y1 <= ROW + 0.5) {
    return `M${n(x1)} ${n(y1)}C${n(x1)} ${n(y1 + half)} ${n(x2)} ${n(y2 - half)} ${n(x2)} ${n(y2)}`;
  }
  const first = y1 + ROW;
  const last = y2 - ROW;
  return (
    `M${n(x1)} ${n(y1)}C${n(x1)} ${n(y1 + half)} ${n(laneAt)} ${n(first - half)} ${n(laneAt)} ${n(first)}` +
    `L${n(laneAt)} ${n(last)}C${n(laneAt)} ${n(last + half)} ${n(x2)} ${n(y2 - half)} ${n(x2)} ${n(y2)}`
  );
}

/** Every line of the tree as one path, for the commits from `from` (a row) down. */
export function treePath(data: HistoryData, geo: Geometry, from = 0): string {
  const rows = new Map(data.commits.map((c, row) => [c.hash, row]));
  const parts: string[] = [];
  data.commits.forEach((commit, row) => {
    if (row < from) return;
    const x1 = laneX(commit.lane);
    const y1 = (geo.top[row] ?? 0) + ROW / 2;
    for (const edge of commit.edges) {
      const parent = rows.get(edge.to);
      const to = parent === undefined ? undefined : data.commits[parent];
      if (parent === undefined || !to) {
        const x = laneX(edge.lane);
        parts.push(
          `M${n(x1)} ${n(y1)}C${n(x1)} ${n(y1 + ROW / 2)} ${n(x)} ${n(y1 + ROW / 2)} ${n(x)} ${n(y1 + ROW)}` +
            `L${n(x)} ${n(geo.height)}`,
        );
      } else {
        parts.push(edgePath(x1, y1, laneX(edge.lane), laneX(to.lane), (geo.top[parent] ?? 0) + ROW / 2));
      }
    }
  });
  return parts.join("");
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** A date as the agent writes it: "5 Mar 2025", in the commit's own time zone. */
export function day(iso: string | null | undefined): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? "");
  if (!match) return "";
  return `${Number(match[3])} ${MONTHS[Number(match[2]) - 1]} ${match[1]}`;
}

/** A span of days: one date when it starts and ends on the same day. */
export function days(start: string, end: string): string {
  const [from, to] = [day(start), day(end)];
  return from === to ? from : `${from} to ${to}`;
}

export function plural(count: number, word: string): string {
  return count === 1 ? `1 ${word}` : `${count} ${word}s`;
}

export function fileHighlight(file: FileLife): Highlight {
  return { label: file.path, rows: new Map(file.events.map((e) => [e.row, e.kind])) };
}

export function commitsHighlight(
  data: HistoryData,
  label: string,
  hashes: string[],
  word: string,
): Highlight {
  const wanted = new Set(hashes);
  const rows = new Map<number, string>();
  data.commits.forEach((c, row) => {
    if (wanted.has(c.hash)) rows.set(row, word);
  });
  return { label, rows };
}

export function toolHighlight(data: HistoryData, tool: string): Highlight {
  const rows = new Map<number, string>();
  data.commits.forEach((c, row) => {
    if (c.ai_tools.includes(tool)) rows.set(row, tool);
  });
  return { label: `Marked as made with ${tool}`, rows };
}

/** Commits where two files changed together, when both files' lives are in the output. */
export function togetherHighlight(data: HistoryData, a: string, b: string, fallback: string[]): Highlight {
  const label = `${a} + ${b}`;
  const first = data.files.find((f) => f.path === a);
  const second = data.files.find((f) => f.path === b);
  if (!first || !second) return commitsHighlight(data, label, fallback, "together");
  const inSecond = new Set(second.events.map((e) => e.row));
  const rows = new Map<number, string>();
  for (const event of first.events) {
    if (inSecond.has(event.row)) rows.set(event.row, "together");
  }
  return { label, rows };
}

/** What happened to a file, in a sentence. */
export function lifeSentence(file: FileLife, commits: Commit[]): string {
  const count = (kind: string) => file.events.filter((e) => e.kind === kind).length;
  const oldest = file.events[file.events.length - 1];
  const parts: string[] = [];
  if (oldest?.kind === "added") parts.push(`added ${day(commits[oldest.row]?.date)}`);
  else parts.push("here before the oldest commit shown");
  if (count("changed")) parts.push(`changed ${plural(count("changed"), "time")}`);
  const renames = file.events.filter((e) => e.kind === "renamed" && e.was);
  const renamed = renames[renames.length - 1];
  if (renamed) parts.push(`renamed from ${renamed.was}`);
  parts.push(file.alive ? "still there" : `deleted ${day(commits[file.events[0]?.row ?? -1]?.date)}`);
  return `${parts.join(", ")}.`;
}
