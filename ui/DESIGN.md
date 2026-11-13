# Design notes

How the web UI looks and behaves, and the reasons behind it.

## The margin

margin's agents show their work, and the name says where that work goes. So every page is
ruled like a sheet of paper. A thin red line runs down it from top to bottom. Left of the
line is the margin, and it holds notes: the name of a section, a count, when a run started,
which model it used. Right of the line is the content the note is about.

Everything on a page is one of these rows (`Block`, or the `m-grid` class for lists whose
rows carry their own notes). Labels are right-aligned against the line and content starts
after it, so the line is the one axis the whole page hangs from. On a phone the margin folds
away: notes sit above their content and the line moves to the edge.

The idea repeats where it is most useful. In the AI Code Detector's result, the notes on
marked code sit in the code's own margin, level with the lines they are about.

There are no cards, no avatars and no hero. Sections are separated by hairlines. A list
starts with one firm rule.

## Colour

Paper, ink, and an editor's two-ended pencil.

- Red marks what is flagged: evidence that reads AI-like, a warning, an answer nobody
  confirmed, a run that needs you.
- Blue marks what is checked: evidence that reads human-like, a number that was recomputed,
  a run in progress, keyboard focus.

Nothing else is coloured. The primary action is filled with ink, and there is one per view.
Links are underlined. If something is red or blue, an agent or a check put it there. The
one exception is the margin line itself, a faded red like the line on ruled paper; it never
marks anything.

The tokens are in `src/styles/theme.css`, written by hand. Each one holds its light and dark
value with `light-dark()`, so the theme switch only changes `color-scheme`.

## Type

Three voices, so you can tell who is speaking:

- Archivo, a grotesque, is the interface: titles, labels, buttons.
- Newsreader, a serif, is whatever an agent wrote: summaries, findings, the story, the last
  thing a running agent said, the estimate itself.
- JetBrains Mono is evidence: code, paths, ids, measured numbers.

All three are bundled (SIL Open Font License). Text is in sentence case. Capitals are kept
for a few small column labels.

## Measuring

Numbers are drawn on rulers. Run progress, the detector's 0 to 1 scale and score meters
all use the same ticks. A weight is a bar that grows from a centre line, red to the right
and blue to the left.

## Shape and motion

Corners are 2px. Controls have a 1px border and a white fill. Shadows appear only on things
that float over the page (the agent menu, the fact panel).

Motion is short and only shows a change of state: a page settling in, a panel opening, the
progress needle moving. With `prefers-reduced-motion` it goes away.

## Where things are

- `src/styles/`: `theme.css` (colour), `tokens.css` (type, the margin grid, small shared
  classes), `base.css` (resets).
- `src/components/Block.tsx`: the margin row and the list head.
- `src/components/Shell.tsx`: the top bar and the footer.
- Icons are Phosphor, regular weight, used sparingly. `src/components/icons.ts` lists every
  one the UI uses.
