# Changelog

All notable changes to this package are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.2] - 2026-11-02

### Added
- Uploads: `POST /uploads?name=<file>` saves the request body as a file and returns its path,
  for an agent's input. Uploads have their own size limit, `MARGIN_API_MAX_UPLOAD_BYTES`
  (200 MB), and are deleted after the result TTL.
- Run files: an input field marked `"format": "output-dir"` and left empty gets a folder of
  the run's own. The run view lists what the run wrote there (`files`), and
  `GET /runs/{run_id}/files/{name}` downloads it. The folder goes when the run is forgotten.
- `MARGIN_API_FILES_DIR` sets where uploads and run files are kept (a temporary folder,
  removed on shutdown, when not set).
- The web UI uploads a file for an input field marked `"format": "file-path"` (drop it or
  choose it, on the agent page and in the home page launcher), and offers a run's files for
  download next to the JSON and Markdown exports.

### Security
- Requests that change something are refused with 403 if they come from another web page. CORS
  only hid the answer, so any site you visited could upload files. Requires FastAPI 0.132 or
  later, which also stops a page from starting a run with a JSON body and no `Content-Type`.
- `MARGIN_API_CORS_ORIGINS` is now empty by default. The UI the API serves itself is unaffected;
  to use the UI's dev server, add `http://localhost:3000` (see `ui/README.md`).
- An output folder can no longer be chosen over HTTP (422), so a caller can't write files
  elsewhere on the machine. Each run writes to its own folder.
- A `.env` in the current folder is no longer read, because it could open the server to the
  network. Name a file with `MARGIN_ENV_FILE`.

## [0.1.1] - 2026-10-29

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
