# margin web UI

A web page for running margin agents. It talks only to the HTTP API: pick an agent, fill
in a form generated from its input schema, watch the run live, and read the result with all
its evidence.

It is designed as a lab notebook: warm paper, ink, and a highlighter that marks the evidence.
[DESIGN.md](DESIGN.md) explains the choices.

## Running it

You need Node 20 or newer, and the API running:

```bash
uv run margin-api            # from the repository root: http://127.0.0.1:8000

cd ui
npm install
npm run dev                  # http://localhost:3000
```

The API only accepts browser requests from `localhost:3000` and `127.0.0.1:3000` by default
(`MARGIN_API_CORS_ORIGINS`). To point the UI at another API address, set `VITE_API_URL`:

```bash
VITE_API_URL=http://127.0.0.1:9000 npm run dev
```

`npm run build` writes a static site to `dist/`, which any web server can host.

## What's in it

| Page | What it does |
|---|---|
| Home | The library's front page: a card for every installed agent, a launcher (pick an agent, paste its main input, run; it remembers the last agent used), and recent runs. |
| Agents | Every installed agent, plus any that failed to load and why. |
| Agent | The input form, generated from the agent's JSON schema: the main input first, other fields under "More options". It also shows the same run as a `margin run` command. An agent can add its own intro beside the form (`agentIntroFor` in `src/results/registry.ts`); the AI Code Detector's explains how it reads code. |
| Run | Live progress over server-sent events: stage, percentage, queue position. You can cancel from here. When the agent asks a question, the run waits and a form shows the questions, the evidence behind them and the suggested answers; it carries on once you answer. When the run finishes, the result appears below. |
| Runs | Recent runs. They live in the API's memory for an hour. |
| Settings | The model agents use: a local server (Ollama, LM Studio, llama.cpp, vLLM), Anthropic or OpenAI, picked from the provider's live model list, with keys and a connection test. A run can also use a different model, chosen on its form. |

Results use a generic viewer that works for any agent: the summary, findings with expandable
evidence, warnings, the answers given to the agent's questions (with who gave each, and
defaults nobody confirmed highlighted), run details, the raw JSON, and export to JSON or
Markdown. An agent can
have its own view instead. Register it in `src/results/registry.ts` under the agent's id.

The AI Code Detector has one (`src/results/detector/`):
- the estimate on a 0 to 1 scale with its range, the confidence and why, and a permanent
  "estimate, not proof" note;
- the evidence for and against, side by side; click any item to open the code;
- a file tree coloured by likelihood, with unscored files greyed out;
- the file's code with marked lines and the reasons beside them;
- the commit history, showing commits that name an AI tool and unusually large ones.

## Development

```bash
npm test                     # unit and component tests (Vitest)
npm run typecheck
npx biome check .            # lint and format check (npx biome check --write . to fix)
```

Generated files (do not edit by hand):

| File | Regenerate with | When |
|---|---|---|
| `src/api/schema.d.ts` | `npm run gen:api` | The API changed (`ui/openapi.json` is updated by `scripts/export_openapi.py`) |
| `src/styles/theme.css` | `npm run gen:theme` | To change the palette or the springs |
| `src/styles/fonts.css`, `public/fonts/` | `npm run fetch:fonts` | To change or update the fonts |

The fonts are bundled, so the UI works offline: Fraunces, Instrument Sans and JetBrains
Mono, all under the SIL Open Font License (texts in `public/fonts/`). Icons are Phosphor
(MIT), and only the ones listed in `src/components/icons.ts` end up in the bundle.
