/**
 * The Commit Graph's `data` (its CommitGraphOutput model), as its view uses it. Results
 * arrive as untyped JSON, so `asHistoryData` checks the shape first; anything unexpected
 * falls back to the generic viewer.
 */

export interface Edge {
  to: string;
  lane: number;
}

export interface Note {
  kind: "root" | "merge" | "big" | "revert" | "gap" | "fix" | "ai";
  text: string;
  flagged?: boolean;
}

export interface Commit {
  hash: string;
  short: string;
  parents: string[];
  lane: number;
  edges: Edge[];
  author: string;
  date: string;
  subject: string;
  tags: string[];
  branches: string[];
  files_changed: number;
  files: string[];
  chapter: number;
  notes: Note[];
  ai_tools: string[];
}

export interface TextPart {
  text: string;
  commit?: string | null;
}

export interface Chapter {
  index: number;
  title: string;
  summary: TextPart[];
  written_by: "model" | "template";
  start: string;
  end: string;
  first_row: number;
  last_row: number;
  commits: number;
  merges: number;
  areas: { path: string; share: number }[];
  tags: string[];
}

export interface Hotspot {
  path: string;
  touches: number;
  lines?: number | null;
  last_changed: string;
  commits: string[];
}

export interface Coupling {
  a: string;
  b: string;
  together: number;
  a_touches: number;
  b_touches: number;
  share: number;
  commits: string[];
}

export interface FixChain {
  commits: string[];
  minutes: number;
  files: string[];
}

export interface OnePersonArea {
  path: string;
  touches: number;
  share: number;
}

export interface FileEvent {
  row: number;
  kind: "added" | "changed" | "renamed" | "deleted";
  was?: string | null;
}

export interface FileLife {
  path: string;
  alive: boolean;
  touches: number;
  events: FileEvent[];
}

export interface AiMark {
  tool: string;
  commits: number;
  first_seen: string;
  first_commit: string;
}

export interface RepoInfo {
  name: string;
  branch?: string | null;
  head?: string | null;
  total_commits: number;
  shown: number;
  truncated: boolean;
  first_date?: string | null;
  last_date?: string | null;
  authors: number;
  lanes: number;
  renames_followed: "exact" | "similar";
}

export interface HistoryData {
  repo: RepoInfo;
  commits: Commit[];
  chapters: Chapter[];
  hotspots: Hotspot[];
  couplings: Coupling[];
  fix_chains: FixChain[];
  one_person_areas: OnePersonArea[];
  files: FileLife[];
  ai_marks: AiMark[];
  poster?: string | null;
}

export function asHistoryData(data: unknown): HistoryData | null {
  if (!data || typeof data !== "object") return null;
  const d = data as Partial<HistoryData>;
  if (!d.repo || typeof d.repo.name !== "string") return null;
  if (!Array.isArray(d.commits) || !Array.isArray(d.chapters)) return null;
  if (d.commits.some((c) => !c || typeof c.hash !== "string" || !Array.isArray(c.edges))) return null;
  return {
    ...d,
    hotspots: d.hotspots ?? [],
    couplings: d.couplings ?? [],
    fix_chains: d.fix_chains ?? [],
    one_person_areas: d.one_person_areas ?? [],
    files: d.files ?? [],
    ai_marks: d.ai_marks ?? [],
  } as HistoryData;
}
