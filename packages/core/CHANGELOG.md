# Changelog

All notable changes to this package are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.3] - 2026-11-02

### Security
- A folder being analysed could still make git run a program named in its `.git/config`, through
  a signed commit (`log.showSignature` with `gpg.program`) or a missing object that made git
  fetch (`core.sshCommand`, `remote.<name>.uploadpack`). Both are closed: signatures aren't
  checked, and reading history never uses the network.
- A `.env` in the current folder was read automatically, so a repository could change margin's
  settings, for example to send its code to another server. Now only a file named by
  `MARGIN_ENV_FILE` is read. **If you keep settings in `.env`, set `MARGIN_ENV_FILE=.env`.**
- Reports no longer carry control characters, which could rewrite what a terminal shows.

## [0.1.2] - 2026-10-29

### Added
- Agents can ask the person running them: `await ctx.ask(questions, title=...)` puts one or
  more `Question`s (choice, multiple choice or text, with a default and evidence) to whoever
  runs the agent and returns the answers. `RunContext(responder=...)` decides how they are
  asked; without a responder, questions take their defaults.
- `AnswersInput`: a base input model with the standard `answers` (given up front, not asked)
  and `assume_defaults` fields.
- `RunMetadata.answers` keeps every answer and who gave it (`user`, `preset` or `default`).
  Defaults nobody confirmed are also reported as warnings. The Markdown report lists the
  answers.
- `NoAnswerError` for a question that could not be answered.

## [0.1.1] - 2026-10-21

### Security
- A repository's own git config could make git run a program while margin read its history,
  for example through `core.fsmonitor`. Every git command now overrides the repository's
  config, turns hooks off and skips Git LFS downloads. This mattered most in Docker, where
  git's own ownership check is turned off for the shared folder.
- Cancelling a run while a repository was being cloned could leave a half-written clone in
  the temp folder. git now runs as a child process that is stopped before the folder is
  deleted.

## [0.1.0] - 2026-10-21

### Added
- The agent contract (`BaseAgent`, `RunContext`), structured results with findings and evidence, and the agent registry (entry-point group `margin.agents`).
- Model clients: local OpenAI-compatible servers (Ollama by default), Anthropic and OpenAI, with retries, token and cost tracking, per-run budgets, and a mock for tests.
- A model catalogue: list a provider's models, test a connection.
- Settings from environment variables, saved settings, `.env` and defaults, in that order.
- Code loaders: local folders and GitHub repositories, with filters, size limits, a pre-clone size check and git history.
- JSON and Markdown reports.
