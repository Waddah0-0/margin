# Changelog

All notable changes to this package are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Runs can stop to ask a question. A run whose agent asks moves to the new `waiting` status,
  sends a `question` event and shows the questions in `GET /runs/{run_id}`;
  `POST /runs/{run_id}/answers` answers them. While waiting, a run gives its place in the
  queue to others, and it stops after `MARGIN_API_ANSWER_TIMEOUT_S` (an hour) without answers.
- `last_event` in the run view: the number of the latest event it already includes, so a
  client can tell replayed events from new ones.
- The web UI shows an agent's questions as a form on the run page, and every result lists
  the answers and who gave them.

### Changed
- `waiting` is a new run status. A client that lists every status must handle it.

### Fixed
- Opening a run page directly (a link or a reload) with the UI served by the API showed
  "Can't reach the API": the browser answered the UI's own request for the run with the
  cached page. Page loads now send `Vary: Accept` and `Cache-Control: no-cache`.

## [0.1.0] - 2026-10-21

### Added
- Background runs with live progress (server-sent events), queue positions and cancellation.
- Model settings over HTTP: provider, models, keys (never returned), live model lists and a connection test.
- The web UI, bundled in the package and served from the same address.
- Answers only to `localhost` by default (protects against DNS rebinding).
