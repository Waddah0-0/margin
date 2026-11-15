# Commit Graph

Draws a repository's history as its tree and tells the story in it: chapters, notes beside
the commits, and the files that keep changing.

> **Status: experimental.** The graph, the chapters, the findings and the poster work and are
> tested. It is not on PyPI yet.

## What it does

Give it a repository and it gives you back its history in a form you can read. The commits
are drawn as a tree, with every branch in its own lane. The history is split into chapters,
each with a title and a short summary. Beside single commits there are notes: a merged
branch and how long it was open, a commit that touched a lot of files, a revert, a long quiet
gap.

It also reports what a plain graph doesn't show:

- **Files that change the most.** Large code files that keep changing.
- **Files that change together.** Code files in different folders that nearly always change
  in the same commit.
- **Runs of quick fixes.** A commit followed within the hour by fix after fix to the same
  files.
- **Areas with one author.** Parts of the repository where one person made nearly every
  change. The person is not named.
- **AI tool marks.** Commits whose message says an AI tool took part. These are reported as
  found and are not a score.

Every count comes from the history. The model, when there is one, only writes the chapter
titles and summaries.

## How it works

1. It loads the repository (a local path, or a GitHub URL that margin clones without file
   contents) and reads the history with one `git log`, asking only for names and statuses.
2. It gives every commit a lane and every line to a parent a lane to run in, so the tree can
   be drawn.
3. It follows each file through adds, changes, renames and deletes.
4. It writes the notes and counts the findings. The thresholds are constants at the top of
   `insights.py`.
5. It splits the history into at most ten chapters. A tag ends a chapter, and so does a quiet
   gap much longer than usual.
6. It writes each chapter. The model gets commit messages, the chapter's areas and its tags.
   It may point at a commit by its short hash and may not write numbers; a draft that breaks
   a rule is sent back once. After that, or without a model, a template writes the chapters.
7. With `output_dir`, it draws the poster: the whole tree as one SVG, with chapter titles in
   the margin.

## Input

| Field | Default | Meaning |
|---|---|---|
| `target` | required | GitHub URL or local path. The primary input. |
| `branch` | the main branch | Branch to read, for GitHub targets. |
| `paths` | empty | Only the history of these folders or files. |
| `max_commits` | 500 | How many commits to draw, counted back from the newest (up to 3000). |
| `write_with_model` | `true` | Let the model write the chapters. Without a model, a template does. |
| `output_dir` | empty | Folder for the poster. In the web UI every run gets one. |

## Output

`data` contains:

- `repo`: name, branch, how many commits there are and how many are shown, the date range,
  the number of lanes.
- `commits`, newest first: hash, parents, `lane`, `edges` (one per parent, with the lane its
  line runs in), author name, date, subject, tags, the first few changed files, its chapter,
  its `notes` and any `ai_tools`.
- `chapters`, oldest first: title, summary (in parts, so a cited commit can be a link), who
  wrote it (`model` or `template`), dates, rows, counts, areas and tags.
- `hotspots`, `couplings`, `fix_chains`, `one_person_areas`, `ai_marks`: the findings, with
  the commits behind them.
- `files`: the life of the 300 most-changed files, as events on rows of the graph.
- `poster`: the poster's file name, when one was written.

The same findings are returned as `findings`, each with its evidence.

## Limits

- It reads names, not contents. It can't say how many lines a commit changed, and in a
  GitHub clone it only follows a rename when the file's contents did not change at all
  (`renames_followed` says which).
- It shows the history of one branch. Branches that were never merged into it are not drawn.
- Beyond `max_commits` the history is cut, and counts only cover the commits shown.
- Squashed and rebased history looks straight. A branch that was squash-merged leaves no
  lane.
- The findings are signs to look at, not verdicts. Two files changing together may be right
  for that code. A run of quick fixes may be someone working in small steps.
- AI tool marks only find tools that sign their commits. No mark does not mean no AI.
- Commit messages are untrusted text. They go to the model as data, and the validator
  refuses a draft that cites a commit the chapter does not have.

## Usage

```bash
margin run commit-graph https://github.com/psf/requests
margin run commit-graph . --set max_commits=1000 --set output_dir=out
margin run commit-graph . --set write_with_model=false --format json
```

## Development

This agent lives in the [margin](https://github.com/Waddah0-0/margin) monorepo, in
[`agents/commit_graph`](https://github.com/Waddah0-0/margin/tree/main/agents/commit_graph). If you are reading this in its mirror
repository, that copy is read-only: open issues and pull requests in the main repository.

Run its tests with `uv run pytest agents/commit_graph`.
