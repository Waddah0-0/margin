import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { AgentResult, RunView } from "../../api/client";
import { HistoryResult } from "./HistoryResult";
import { CHAPTER_ROW, day, days, edgePath, geometry, lifeSentence, ROW, treePath } from "./logic";
import type { Commit, FileLife, HistoryData } from "./types";

const full = (short: string) => short.padEnd(40, "0");

function commit(short: string, parents: string[], extra: Partial<Commit> = {}): Commit {
  return {
    hash: full(short),
    short,
    parents: parents.map(full),
    lane: 0,
    edges: parents.map((p, i) => ({ to: full(p), lane: i })),
    author: "Ada",
    date: "2025-01-05T12:00:00+00:00",
    subject: `commit ${short}`,
    tags: [],
    branches: [],
    files_changed: 1,
    files: ["src/app.py"],
    chapter: 2,
    notes: [],
    ai_tools: [],
    ...extra,
  };
}

const appLife: FileLife = {
  path: "src/app.py",
  alive: true,
  touches: 3,
  events: [
    { row: 2, kind: "renamed", was: "src/old.py" },
    { row: 3, kind: "changed" },
    { row: 4, kind: "added" },
  ],
};

const data: HistoryData = {
  repo: {
    name: "demo",
    branch: "main",
    total_commits: 5,
    shown: 5,
    truncated: false,
    first_date: "2025-01-01T12:00:00+00:00",
    last_date: "2025-01-09T12:00:00+00:00",
    authors: 2,
    lanes: 2,
    renames_followed: "similar",
  },
  commits: [
    commit("mmmmmmm", ["ccccccc", "bbbbbbb"], {
      subject: "merged the rename",
      date: "2025-01-09T12:00:00+00:00",
      notes: [{ kind: "merge", text: "Merged a branch of 1 commit" }],
      files: [],
      files_changed: 0,
    }),
    commit("ccccccc", ["aaaaaaa"], { subject: "added a readme", ai_tools: ["Claude"] }),
    commit("bbbbbbb", ["aaaaaaa"], {
      subject: "reverted the app",
      lane: 1,
      edges: [{ to: full("aaaaaaa"), lane: 1 }],
      notes: [{ kind: "revert", text: "Undid an earlier commit", flagged: true }],
    }),
    commit("aaaaaaa", ["rrrrrrr"], { subject: "changed the app", chapter: 1, tags: ["v0.1.0"] }),
    commit("rrrrrrr", [], {
      subject: "added the app",
      chapter: 1,
      date: "2025-01-01T12:00:00+00:00",
      notes: [{ kind: "root", text: "The first commit" }],
    }),
  ],
  chapters: [
    {
      index: 1,
      title: "The beginning",
      summary: [{ text: "It started with " }, { text: "rrrrrrr", commit: full("rrrrrrr") }, { text: "." }],
      written_by: "model",
      start: "2025-01-01T12:00:00+00:00",
      end: "2025-01-01T18:00:00+00:00",
      first_row: 3,
      last_row: 4,
      commits: 2,
      merges: 0,
      areas: [{ path: "src/", share: 1 }],
      tags: ["v0.1.0"],
    },
    {
      index: 2,
      title: "Work on src/",
      summary: [{ text: "Three commits over five days." }],
      written_by: "template",
      start: "2025-01-05T12:00:00+00:00",
      end: "2025-01-09T12:00:00+00:00",
      first_row: 0,
      last_row: 2,
      commits: 3,
      merges: 1,
      areas: [],
      tags: [],
    },
  ],
  hotspots: [
    { path: "src/app.py", touches: 4, lines: 120, last_changed: "2025-01-05T12:00:00+00:00", commits: [] },
  ],
  couplings: [],
  fix_chains: [],
  one_person_areas: [{ path: "docs/", touches: 30, share: 0.97 }],
  files: [appLife],
  ai_marks: [
    { tool: "Claude", commits: 1, first_seen: "2025-01-05T12:00:00+00:00", first_commit: full("ccccccc") },
  ],
};

const result = {
  agent_id: "commit-graph",
  agent_version: "0.1.0",
  status: "ok",
  summary: "Five commits.",
  data,
  findings: [],
  warnings: [],
  metadata: {},
} as unknown as AgentResult;
const run = { run_id: "0123456789abcdef", agent_id: "commit-graph", files: [] } as unknown as RunView;

const rowOf = (subject: string) =>
  [...document.querySelectorAll<HTMLButtonElement>("[data-row]")].find((row) =>
    row.textContent?.includes(subject),
  ) as HTMLButtonElement;

describe("the geometry of the tree", () => {
  it("puts the heading of a chapter above its newest commit", () => {
    const geo = geometry(data);
    expect(geo.top).toEqual([
      CHAPTER_ROW,
      CHAPTER_ROW + ROW,
      CHAPTER_ROW + 2 * ROW,
      2 * CHAPTER_ROW + 3 * ROW,
      2 * CHAPTER_ROW + 4 * ROW,
    ]);
    expect([...geo.chapterTop]).toEqual([
      [2, 0],
      [1, CHAPTER_ROW + 3 * ROW],
    ]);
    expect(geo.height).toBe(2 * CHAPTER_ROW + 5 * ROW);
  });

  it("draws a neighbour as one curve and a far parent through its lane", () => {
    expect(edgePath(9, 15, 9, 9, 45)).toBe("M9.0 15.0C9.0 30.0 9.0 30.0 9.0 45.0");
    const far = edgePath(9, 15, 23, 9, 135);
    expect(far).toContain("L23.0 105.0");
    expect(far.endsWith("9.0 135.0")).toBe(true);
  });

  it("leaves out commits newer than the replay, and runs a missing parent to the bottom", () => {
    const geo = geometry(data);
    expect(treePath(data, geo, 0).split("M").length - 1).toBe(5);
    expect(treePath(data, geo, 3).split("M").length - 1).toBe(1);
    const cut = { ...data, commits: data.commits.slice(0, 4) };
    expect(treePath(cut, geometry(cut), 3)).toContain(`L9.0 ${geometry(cut).height.toFixed(1)}`);
  });

  it("writes dates the way the agent does", () => {
    expect(day("2025-03-05T23:30:00-08:00")).toBe("5 Mar 2025");
    expect(days("2025-01-01T12:00:00+00:00", "2025-01-01T18:00:00+00:00")).toBe("1 Jan 2025");
    expect(lifeSentence(appLife, data.commits)).toBe(
      "added 1 Jan 2025, changed 1 time, renamed from src/old.py, still there.",
    );
  });
});

describe("HistoryResult", () => {
  it("shows the repository, the chapters, the findings and every commit", () => {
    render(<HistoryResult run={run} result={result} />);
    expect(screen.getByText("demo")).toBeTruthy();
    expect(screen.getByText("5 commits, 1 Jan 2025 to 9 Jan 2025, by 2 people")).toBeTruthy();
    expect(screen.getByText("Written by the model from the commit messages")).toBeTruthy();
    expect(screen.getAllByText("The beginning")).toHaveLength(2);
    expect(screen.getByText("One person made 97% of 30 file changes")).toBeTruthy();
    expect(screen.getByText("4 commits, 120 lines long")).toBeTruthy();
    expect(document.querySelectorAll("[data-row]")).toHaveLength(5);
    expect(document.querySelectorAll("circle")).toHaveLength(5);
    expect(screen.getByText("v0.1.0")).toBeTruthy();
    // notes hang in the margin beside their commit; a flagged one is marked
    const flagged = within(rowOf("reverted the app")).getByText("Undid an earlier commit");
    expect(flagged.hasAttribute("data-flagged")).toBe(true);
    expect(within(rowOf("added the app")).getByText("The first commit")).toBeTruthy();
  });

  it("opens a commit when it is picked, and from a citation in a chapter", async () => {
    const user = userEvent.setup();
    render(<HistoryResult run={run} result={result} />);
    await user.click(rowOf("added a readme"));
    expect(rowOf("added a readme").getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByText(/ccccccc/, { selector: "p code" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "rrrrrrr" }));
    expect(rowOf("added the app").getAttribute("aria-pressed")).toBe("true");
    await user.click(screen.getByRole("button", { name: "Close the commit" }));
    expect(rowOf("added the app").getAttribute("aria-pressed")).toBe("false");
  });

  it("lights up the life of a file on the tree and dims the rest", async () => {
    const user = userEvent.setup();
    render(<HistoryResult run={run} result={result} />);
    await user.click(screen.getByText("4 commits, 120 lines long"));
    expect(screen.getByText(/added 1 Jan 2025, changed 1 time, renamed from src\/old.py/)).toBeTruthy();
    expect(within(rowOf("added the app")).getByText("added")).toBeTruthy();
    expect(within(rowOf("reverted the app")).getByText("renamed")).toBeTruthy();
    expect(rowOf("merged the rename").hasAttribute("data-dim")).toBe(true);
    expect(rowOf("added the app").hasAttribute("data-dim")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(rowOf("merged the rename").hasAttribute("data-dim")).toBe(false);
  });

  it("lights up the commits an AI tool marked", async () => {
    const user = userEvent.setup();
    render(<HistoryResult run={run} result={result} />);
    await user.click(screen.getByText("1 commit, first on 5 Jan 2025"));
    expect(screen.getByText("Marked as made with Claude")).toBeTruthy();
    expect(rowOf("added a readme").hasAttribute("data-dim")).toBe(false);
    expect(rowOf("added the app").hasAttribute("data-dim")).toBe(true);
  });

  it("replays the history: the slider hides what had not happened yet", () => {
    render(<HistoryResult run={run} result={result} />);
    const slider = screen.getByLabelText("Replay the history") as HTMLInputElement;
    expect(slider.value).toBe("4");
    expect(screen.getByText("The whole history")).toBeTruthy();
    fireEvent.change(slider, { target: { value: "1" } });
    expect(screen.getByText("Up to 5 Jan 2025 · chapter 1")).toBeTruthy();
    expect(rowOf("merged the rename").hasAttribute("data-hidden")).toBe(true);
    expect(rowOf("changed the app").hasAttribute("data-hidden")).toBe(false);
    expect(document.querySelectorAll("circle")).toHaveLength(2);
  });

  it("falls back to the generic view when the data is not the agent's own", () => {
    render(<HistoryResult run={run} result={{ ...result, data: { something: "else" } } as AgentResult} />);
    expect(screen.queryByText("Chapters")).toBeNull();
    expect(screen.getByText("Five commits.")).toBeTruthy();
  });
});
