# Changelog

All notable changes to this package are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `margin run` asks an agent's questions in the terminal, on stderr, so the report on stdout
  stays clean. Ctrl+C still cancels while a question is open. When input or stderr is not a
  terminal, questions take their defaults and the report marks them as not confirmed.

## [0.1.0] - 2026-10-21

### Added
- `margin list`, `margin info` and `margin run`, with JSON or Markdown reports, progress on stderr, and documented exit codes.
- `--provider` and `--model` choose the model for one run.
