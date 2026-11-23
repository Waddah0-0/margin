# Changelog

All notable changes to this agent are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

### Added
- Initial experimental release of the Secret Leaks agent (`secret-leaks`).
- High-precision detection rules for AWS, GitHub, GitLab, Slack, Stripe, Google, OpenAI, and
  Anthropic tokens, PEM private key headers, credentialed database URLs, and generic quoted
  secret assignments.
- Shannon entropy and placeholder filtering, inline suppression (`# margin:ignore` and
  `pragma: allowlist secret`), and custom `allowlist_patterns` regex filtering.
- Always-on masking so raw secret values never appear in findings, output data, or summaries.
- Workspace and bounded git commit-patch scanning (including historical secrets later deleted
  from `HEAD`, with clean partial-clone detection).
