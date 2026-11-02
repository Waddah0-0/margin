# margin-cli

The `margin` command lists, describes and runs the margin agents you have installed. Install
an agent package and it shows up here, nothing else to configure.

```bash
pip install margin-cli margin-ai-code-detector
margin run ai-code-detector https://github.com/psf/requests
```

## Commands

```bash
margin list [--json]                 # installed agents (and any that failed to load)
margin info <agent> [--json]         # description and input fields
margin run <agent> [INPUT] [options] # run it and print the report
margin version
```

`margin --verbose ...` (or `-v`) prints debug logs on stderr.

## Giving an agent its input

The value after the agent's name fills its main input field, which `margin info` marks as
"positional". For the detector that's the repository URL or path.

`--set field=value` (or `-s`, as many times as you need) sets any other field. A value that
parses as JSON is read as JSON (`3`, `true`, `["a","b"]`), except in text fields, which always
take what you typed. `--input file.json` (`-i`) reads the fields from a JSON file, and `--set`
wins over it.

```bash
margin run ai-code-detector ./my-project --set include_tests=true
margin run ai-code-detector --set target=./my-project --set 'paths=["src"]'
margin run ai-code-detector -i input.json -s max_files_for_judge=5
```

Giving the main field both ways, positionally and with `--set`, is an error.

## Options of `margin run`

| Option | Meaning |
|---|---|
| `--format markdown\|json`, `-f` | Report format. Default: JSON when `--out` ends in `.json`, otherwise Markdown. |
| `--out PATH`, `-o` | Write the report to a file instead of stdout. |
| `--provider NAME` | LLM provider: `local` (default), `anthropic`, `openai` or `mock`. |
| `--model NAME` | Model name, e.g. `qwen3.5:9b`. |
| `--max-cost USD` | Spending limit for this run (only matters for hosted providers). |
| `--quiet`, `-q` | No progress display. |
| `--strict` | Treat a partial result as a failure (exit code 4). |

The model comes from your settings (environment variables, settings saved in the web UI, or
the file named by `MARGIN_ENV_FILE`), but nothing talks to a model unless the agent needs one. Agents that don't use a
model work even with no model server running. If you pass `--provider` or `--model`, that
choice is checked before the run starts.

## Output streams

Only the report goes to stdout. Progress, warnings and errors go to stderr. This keeps
`margin run ... --format json > report.json` valid JSON.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | The run finished with status `ok`, or `partial` without `--strict`. |
| 1 | The run finished with status `error` (the report still explains why). |
| 2 | Bad usage or invalid input. |
| 3 | The agent is not installed, or failed to load. |
| 4 | The run finished with status `partial` and `--strict` was given. |
| 130 | Cancelled with Ctrl+C. |

## Cancelling

Press Ctrl+C once to ask the agent to stop. It gets 5 seconds to finish cleanly, after which
it is stopped. Press Ctrl+C again to stop at once.
