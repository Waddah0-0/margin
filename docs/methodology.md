# How the AI Code Detector scores code

This page explains what the AI Code Detector's numbers mean, how they are produced, and how
far to trust them. It describes methodology v1, used by detector 0.2.0 and later.

In short, the detector is good at ranking repositories, putting the more AI-like ones above
the less AI-like ones, and bad at deciding about any single one. It must not be the basis for
accusing anyone, and the numbers further down show why.

## What goes into the estimate

First, a language model reads a sample of files. By default that's `qwen3.5:9b`, running
locally through Ollama, and it reads up to 20 files per repository: a fixed mix of files the
quick checks consider AI-like, human-like and neither. For each one it gives a likelihood, how
sure it is, and line numbers for the evidence on both sides. The lines quoted in the report
are copied from the file, not from the model's answer, so it can't invent evidence. The code
is wrapped in random markers and the model is told it's data, which stops instructions hidden
in a repository from steering it. A fifth of the files are judged a second time with the
rubric in a different order, and if the two answers disagree a lot, confidence goes down.

Second, quick checks read every Python, JavaScript and TypeScript file: how much commenting
there is, comments that just restate the code, naming habits, personal or informal comments,
commented-out code, and debugging statements left behind.

The two are combined for the whole repository, with weights fitted on data (see below):

```
log-odds = 1.38 + 0.27 x (files' average signal log-odds) + 1.54 x (judge's average log-odds)
```

The judge gets most of the weight because in evaluation it was the only evidence that held up
on recent code.

The range comes from resampling the files 1,000 times and taking the 10th to 90th percentile.
The judge's part is recomputed for each resample, so a verdict based on only a few files gives
a wider range. Resampling only measures how much the files disagree, not how unsure the method
itself is, so the range is also kept at least ±0.15 wide at low confidence and ±0.07 at
medium.

## What is reported but not scored

Traces left by AI tools are reported but never scored: config files such as `CLAUDE.md` or
`.cursorrules`, co-author trailers and bot authors, from nine tools, each checked against a
real commit. They prove a tool was used, not how much of the code it wrote, and anyone can add
or remove them.

Commit history and README style are shown as context only. In evaluation, a long, messy
history told old projects from new ones rather than people from AI, and giving it weight made
every recent human project in the dataset look AI-written.

## Without a model

If no model is configured or reachable, the detector falls back to a signals-only model and
reports low confidence. In evaluation, signals alone ranked repositories only modestly better than
chance and flagged a large share of human repositories.

## How it was measured

Dataset v1 has 70 repositories:

| | Python | JavaScript / TypeScript |
|---|---|---|
| Human, before 2021 | 22 | 10 |
| Human, after 2023 (Gentoo, no-AI policy) | 5 | 0 |
| AI-built, 2025 or later | 16 | 17 |

They were split by repository into train (44), validation (13) and test (13). Weights were
fitted on train only, choices were made on validation, and the test split was scored once.

Results (repository level; `eval/results/v1_final_*.json`):

| | Train (44) | Validation (12) | Test (13) |
|---|---|---|---|
| **With the judge:** AUC | 0.87 | 0.97 | 1.00 |
| False positives at 0.5 | 13% | 29% | 0% |
| AI repositories above 0.5 | 90% | 100% | 83% |
| Calibration error | 0.19 | 0.25 | 0.21 |
| **Signals only:** AUC | 0.73 | 1.00 | 0.79 |
| False positives at 0.5 | 39% | 57% | 29% |

On the test split, every human repository scored at most 0.43, including recent human code
(Gentoo's `portage`, 0.28), and five of six AI repositories scored above 0.5. But the test
split is small. With 7 human and 6 AI repositories, one more mistake would move the AUC by about
0.02-0.03 and the false-positive rate by 14 points. Treat these numbers as encouraging, not
as proof. (One validation repository could not be fetched: its pinned commit was removed
upstream.)

## What the numbers mean for you

Treat the estimate as a way to rank repositories, not as a probability you can quote. The
methodology isn't calibrated, which means its numbers don't match real-world frequencies, and
that's why confidence never goes above medium.

There's no "likely AI" verdict either. A threshold of 0.915 kept false positives at 5% or
less on the training repositories, but it caught only 1 of the 21 AI repositories there. Any
lower threshold starts flagging human projects.

The part worth reading is the evidence: the lines the judge pointed at and the signals that
fired, on both sides.

## Known weaknesses

1. Generated-looking human code scores high. Projects with large, repetitive data files
   (locale tables in `dateparser` and `pendulum`) were judged AI-like.
2. Few recent human projects. Only five, all Python and from one ecosystem. Results on
   other recent human code are uncertain.
3. Agent-built projects only. Code written with light AI help, or AI code edited by people,
   is not represented, and the detector has not been tested on it.
4. Memorisation. Famous pre-2021 projects may be recognised by the model from its training
   data, which inflates results on them.
5. Tool mix. Claude-built repositories are the largest group among the AI samples.

The datasets, results and tools are in `agents/ai_code_detector/eval/`; anyone can re-run them.
