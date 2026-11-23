# Secret Leaks

Scans workspace files and git history for hardcoded secrets, API keys, private keys, and
database credentials, reporting only redacted previews.

> **Status: experimental.** Runs locally with regular expressions and entropy checks; no files
> or matched values are sent to a model. It is not on PyPI yet.

## What it does

Point it at a local folder or a public GitHub repository and it checks current files and recent
git commits for accidentally committed credentials, including secrets added in an earlier commit
and removed before `HEAD`.

## How it works

1. Loads the target through `margin_core` (`ctx.load_workspace`), skipping binaries, lockfiles,
   minified files, files over 1 MB, and tool or build folders (`node_modules`, `.vscode`,
   `dist`, ...). Vendored and generated files are scanned, since secrets end up there too.
   The run warns with what was not scanned.
2. Scans each text file line by line (very long lines in overlapping windows) for provider tokens (AWS, GitHub, GitLab, Slack, Stripe,
   Google, OpenAI, Anthropic), PEM private key headers, database URLs with passwords, and
   generic quoted secret assignments (`api_key`, `secret`, `token`, `password`).
3. Drops common false positives using Shannon entropy thresholds, explicit placeholder checks
   (`example`, `changeme`, `placeholder`, `your_`, `dummy`, `xxxx`, `0000`, `<...>`, `${...}`),
   inline ignore comments (`# margin:ignore`, `pragma: allowlist secret`), and any
   `allowlist_patterns`.
4. When `scan_git_history` is true and the repository has local history, streams added lines
   from up to `history_depth` recent commits using read-only `git log` patches (excluding
   deleted files, lockfiles, binaries, and ignored folders, and capping patch size at 16 MiB).
   Each match records its commit SHA and whether it is still in `HEAD`. PEM keys are matched
   by their whole block, so a key that moved within a file is still found in `HEAD`.
5. Replaces every matched secret with a masked preview (or header label for PEM keys) before
   building findings, output data, or the summary.

## Input

| Field | Default | Meaning |
|---|---|---|
| `target` | required | Local path or GitHub URL (`https://github.com/<owner>/<repo>`). The primary input. |
| `scan_git_history` | `true` | Scan recent git commit patches for introduced or deleted secrets. |
| `history_depth` | `50` | Maximum number of commits to inspect (`1` to `5000`). |
| `paths` | all files | Only scan these relative files or folders. |
| `branch` | default branch | Branch to scan (GitHub URL targets only). |
| `min_severity` | `"low"` | Minimum severity to report: `"low"`, `"medium"`, or `"high"`. |
| `allowlist_patterns` | `[]` | Regular expressions for lines or values to ignore. |

## Output

`data` holds a `SecretLeaksOutput` with:

- `total_matches`, `workspace_matches`, and `git_history_matches`
- `counts_by_severity` (`high`, `medium`, `low`)
- `files_scanned`, `commits_scanned`, and `rules_triggered`
- `matches`: up to 200 `SecretMatchSummary` entries with rule details, severity, source
  (`workspace` or `git_history`), `file_path`, `line`, `commit_sha`, `in_head`, `entropy`, and
  a masked `redacted_preview` (such as `AKIA...12`, `BEGIN RSA PRIVATE KEY`, or `***`).

`findings` lists the same capped entries with file and commit evidence. Raw secret values are
never stored in the result.

## Limits

- Relies on regular expressions and entropy heuristics; custom token formats, split values, or
  obfuscated secrets can be missed.
- Placeholder and entropy filters suppress obvious documentation values and may miss weak or
  synthetic credentials that look like placeholders.
- GitHub URL targets are cloned without historical blobs (`--filter=blob:none`), so git history
  patch scanning is skipped with a warning and `partial` status. Clone the repository locally
  to scan full git history.
- Git history patch scanning stops after 16 MiB of patch output or 120 seconds and marks the
  run `partial`.
- `matches` and `findings` are capped at 200 entries; `total_matches` and `counts_by_severity`
  always reflect all matches found.
- Previews show at most four characters of a secret: a provider's public prefix (`ghp_`,
  `AKIA`) and the last two characters, or for other secrets of 16 characters or more the first
  and last two. Treat any flagged credential as exposed until it is rotated and removed from
  git history.

## Usage

```bash
margin run secret-leaks ./path/to/repo --format markdown
margin run secret-leaks ./path/to/repo --set scan_git_history=false --set min_severity=high
```

```python
import asyncio

from secret_leaks import SecretLeaksAgent


async def main() -> None:
    result = await SecretLeaksAgent().execute({"target": "."})
    print(result.summary)


asyncio.run(main())
```

## Development

This agent lives in the [margin](https://github.com/Waddah0-0/margin) monorepo, in
[`agents/secret_leaks`](https://github.com/Waddah0-0/margin/tree/main/agents/secret_leaks).

Run its tests with `uv run python -m pytest agents/secret_leaks`.
