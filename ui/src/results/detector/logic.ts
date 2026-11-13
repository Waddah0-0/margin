/** Pure helpers for the detector view: the file tree and the evidence columns. */
import type { DetectorData, Side } from "./types";
import { splitLocation } from "./types";

// ---- file tree ------------------------------------------------------------------------

export interface TreeFile {
  kind: "file";
  name: string;
  path: string;
  probability: number | null; // null: not scored
  byModel: boolean; // the score is the model's verdict, not the signals'
  reason?: string; // why it is not scored
  hasExcerpt: boolean;
}

export interface TreeFolder {
  kind: "folder";
  name: string;
  path: string;
  children: TreeNode[];
  scored: number; // scored files below
}

export type TreeNode = TreeFile | TreeFolder;

/**
 * The score to show for a file: the model's likelihood when it read the file (under
 * methodology v1 that is the code-level evidence that counts), else the signals' score.
 */
export function fileScore(f: { probability: number; judge: { likelihood_ai: number } | null }): {
  value: number;
  byModel: boolean;
} {
  return f.judge ? { value: f.judge.likelihood_ai, byModel: true } : { value: f.probability, byModel: false };
}

/** A folder tree of scored files, plus unscored ones when asked, filtered by `query`. */
export function buildTree(
  data: DetectorData,
  { includeUnscored = false, query = "" }: { includeUnscored?: boolean; query?: string } = {},
): TreeFolder {
  const root: TreeFolder = { kind: "folder", name: "", path: "", children: [], scored: 0 };
  const excerpts = new Set(data.excerpts.map((e) => e.path));
  const q = query.trim().toLowerCase();
  const entries: TreeFile[] = data.files.map((f) => ({
    kind: "file",
    name: "",
    path: f.path,
    probability: fileScore(f).value,
    byModel: fileScore(f).byModel,
    hasExcerpt: excerpts.has(f.path),
  }));
  if (includeUnscored) {
    for (const u of data.unscored_files) {
      entries.push({
        kind: "file",
        name: "",
        path: u.path,
        probability: null,
        byModel: false,
        reason: u.reason,
        hasExcerpt: false,
      });
    }
  }
  for (const entry of entries) {
    if (q && !entry.path.toLowerCase().includes(q)) continue;
    // skipped folders (node_modules/, symlinks) end with "/" and show as greyed leaves
    const isDir = entry.path.endsWith("/");
    const parts = entry.path.replace(/\/$/, "").split("/");
    let folder = root;
    for (const [i, part] of parts.entries()) {
      if (i === parts.length - 1) {
        folder.children.push({ ...entry, name: isDir ? `${part}/` : part });
        break;
      }
      const path = parts.slice(0, i + 1).join("/");
      let next = folder.children.find((c): c is TreeFolder => c.kind === "folder" && c.name === part);
      if (!next) {
        next = { kind: "folder", name: part, path, children: [], scored: 0 };
        folder.children.push(next);
      }
      folder = next;
    }
  }
  finish(root);
  return root;
}

function finish(folder: TreeFolder): number {
  let scored = 0;
  for (const child of folder.children) {
    if (child.kind === "folder") scored += finish(child);
    else if (child.probability !== null) scored += 1;
  }
  folder.children.sort((a, b) =>
    a.kind !== b.kind ? (a.kind === "folder" ? -1 : 1) : a.name.localeCompare(b.name),
  );
  folder.scored = scored;
  return scored;
}

/** Folders on the way to `path`, so the tree can open them. */
export function ancestors(path: string): string[] {
  const parts = path.split("/");
  return parts.slice(0, -1).map((_, i) => parts.slice(0, i + 1).join("/"));
}

// ---- evidence for and against ---------------------------------------------------------

export interface EvidenceEntry {
  side: "for" | "against";
  source: "judge" | "signal";
  text: string;
  quote?: string;
  path?: string;
  line?: number;
  location?: string;
  weight?: number;
}

const FOR_TITLE = "Evidence toward AI assistance";
const AGAINST_TITLE = "Evidence toward human authorship";

/**
 * Both columns: the judge's quotes (the strongest evidence under methodology v1), from the
 * most to the least likely file, then the ranked signals from the report's findings.
 */
export function collectEvidence(
  data: DetectorData,
  findings: {
    title: string;
    evidence?: { kind: string; location?: string | null; detail: string; weight?: number | null }[];
  }[],
): Record<"for" | "against", EvidenceEntry[]> {
  const columns: Record<"for" | "against", EvidenceEntry[]> = { for: [], against: [] };
  const byLikelihood = [...data.files]
    .filter((f) => f.judge)
    .sort((a, b) => (b.judge?.likelihood_ai ?? 0) - (a.judge?.likelihood_ai ?? 0));
  for (const f of byLikelihood) {
    for (const [side, quotes] of [
      ["for", f.judge?.evidence_for ?? []],
      ["against", f.judge?.evidence_against ?? []],
    ] as const) {
      for (const q of quotes) {
        columns[side].push({
          side,
          source: "judge",
          text: q.why,
          quote: q.quote,
          path: f.path,
          line: q.line_start,
          location: `${f.path}:${q.line_start}`,
        });
      }
    }
  }
  for (const [side, title] of [
    ["for", FOR_TITLE],
    ["against", AGAINST_TITLE],
  ] as const) {
    const finding = findings.find((f) => f.title === title);
    for (const ev of finding?.evidence ?? []) {
      const where = splitLocation(ev.location);
      columns[side].push({
        side,
        source: "signal",
        text: ev.detail,
        path: where && ev.kind === "file" ? where.path : undefined,
        line: where?.line,
        location: ev.location ?? undefined,
        weight: ev.weight ?? undefined,
      });
    }
  }
  return columns;
}

/** Findings the detector view shows in its own sections, so the "more" list skips them. */
export const SHOWN_ELSEWHERE = new Set([
  "Estimated likelihood of AI assistance",
  "AI tool usage confirmed by metadata",
  FOR_TITLE,
  AGAINST_TITLE,
  "How to read this result",
]);

/**
 * A colour for a likelihood: blue pencil towards 0 (human-like), red towards 1 (AI-like),
 * and plain grey in the middle, where the evidence says little either way.
 */
export function probabilityColor(p: number): string {
  const t = Math.max(0, Math.min(1, p));
  const strength = Math.round(Math.abs(t - 0.5) * 200);
  return `color-mix(in oklab, var(${t >= 0.5 ? "--red" : "--blue"}) ${strength}%, var(--ink-3))`;
}

export const SIDE_LABEL: Record<Side, string> = {
  for: "Toward AI",
  against: "Toward a human",
  context: "Context only",
};

export const REASON_LABEL: Record<string, string> = {
  unsupported_language: "language not analysed",
  test_file: "test file (not scored by default)",
  too_small: "too small to judge",
  unparseable: "could not be parsed",
  unreadable: "could not be read",
  lockfile: "lockfile",
  binary: "binary file",
  minified: "minified",
  generated: "generated code",
  vendored: "vendored code",
  too_large: "too large",
  ignored_dir: "ignored folder",
  ignored_glob: "ignored by pattern",
  symlink: "symlink",
};
