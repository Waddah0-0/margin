# Releasing

margin publishes five packages to PyPI: `margin-core`, `margin-cli`, `margin-api` (which
bundles the web UI), `margin-ai-code-detector` and `margin-data-storyteller`. Anything marked
`Private :: Do Not Upload` (the echo fixture, and every new agent until it is ready) is never
uploaded.

## One-time setup

Publishing uses PyPI's *trusted publishing*: PyPI trusts this repository's
`.github/workflows/release.yml` directly, so no password or token is stored anywhere.

On [pypi.org](https://pypi.org) (and, for dry runs, [test.pypi.org](https://test.pypi.org),
which is a separate account), go to **Account settings → Publishing → Add a new pending
publisher** and add one entry per package:

| Field | Value |
|---|---|
| PyPI project name | `margin-core`, then `margin-cli`, `margin-api`, `margin-ai-code-detector`, `margin-data-storyteller` |
| Owner | `Waddah0-0` |
| Repository name | `margin` |
| Workflow name | `release.yml` |
| Environment name | `pypi-` + the project name, e.g. `pypi-margin-core` (on test.pypi.org: `testpypi-margin-core`) |

Each package has its own environment because PyPI does not accept the same pending publisher
for several new projects. PyPI also allows only three pending publishers at a time, so for
a fourth new package, publish the first three, then add the fourth and re-run its job. The first upload turns each pending publisher into the project's
real one. A new agent needs its own entry, and its own line in the publish matrix of
`release.yml` (the release check fails until it has one).

## Each release

1. Bump the `version` of each package that changed, and move its `CHANGELOG.md` entry from
   "Unreleased" to the version and date. Packages depend on `margin-core` with a range
   (`>=0.1.0,<0.2`); when core makes a breaking change, raise its minor version and every
   dependent's range together.
2. Check locally, exactly as the workflow will:

   ```bash
   uv run python scripts/build_release.py
   ```

   It builds the UI into `margin-api`, builds every package, checks the metadata, then
   installs the wheels into a fresh environment and runs `margin` and `margin-api`.
3. Optional dry run: **Actions → Release → Run workflow → testpypi**, then try
   `pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ margin-cli`.
4. Tag and push:

   ```bash
   git tag v0.1.0 && git push origin v0.1.0
   ```

   The workflow builds, checks and publishes. Versions already on PyPI are skipped, so a tag
   only publishes the packages whose version changed.

A version on PyPI can never be replaced, only yanked (hidden from new installs). If something
is wrong, fix it and publish the next version.
