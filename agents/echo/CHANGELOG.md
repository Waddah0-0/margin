# Changelog

All notable changes to this agent are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [0.1.0] - Unreleased

### Added
- Echo a message, optionally repeated, and optionally ask the model to reply.
- `message` is the primary input.
- `message` carries an example value for forms.
- `ask` asks how to echo the message (as typed or in capitals) before echoing it: the
  smallest example of an agent asking a question. `answers` and `assume_defaults` come from
  `AnswersInput`.
