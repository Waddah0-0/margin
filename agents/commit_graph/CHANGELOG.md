# Changelog

All notable changes to this agent are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-27

### Added
- The history of a repository as a tree: a lane for every commit and for every line to a
  parent, from name-only `git log`, so it also works in a blobless clone.
- Chapters, split at tags and long quiet gaps. A template writes them; with a model, the model
  does, and may only cite commits it was shown and write no numbers.
- Notes beside commits: the first commit, a merged branch and how long it was open, a commit
  that touched many files, a revert, a long quiet gap, a quick fix.
- Findings: files that change the most, files in different folders that change together, runs
  of quick fixes, areas with one author (not named), and AI tool marks in commit messages.
- The life of each file across renames, as events on the graph.
- `output_dir`: a poster of the whole tree as one SVG.
