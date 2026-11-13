/**
 * The Data Storyteller's own result view: the story page by page, with its charts, and
 * every number a button that opens the fact behind it (how it was computed, on how many
 * rows, how sure it is, and that DuckDB got the same number). Below the story: how the
 * data was cleaned and what each column holds. A run without a story (cleaning only)
 * uses the generic viewer.
 */
import { type ReactNode, useEffect, useMemo, useState } from "react";
import { Block } from "../../components/Block";
import { Icon } from "../../components/Icon";
import {
  ExportButtons,
  GenericResult,
  ResultFooter,
  ResultLayout,
  Section,
  StatusBanner,
} from "../GenericResult";
import type { ResultViewProps } from "../registry";
import { ChartFigure } from "./charts";
import styles from "./storyteller.module.css";
import { asStorytellerData, type Fact, type StorySentence, type StorytellerData } from "./types";

const DECIDED = {
  rule: "By rule",
  user: "You chose",
  preset: "Given with the run",
  default: "Assumed",
} as const;

const ROLE = {
  pulse: "The pulse",
  drivers: "What drives it",
  nuance: "The nuance",
  actions: "Next",
} as const;

/** Split off the punctuation touching a number ("(", ", "), so it wraps with the number. */
function edges(text: string): { lead: string; head: string; tail: string } {
  const head = /^[^\s]*/.exec(text)?.[0] ?? "";
  const rest = text.slice(head.length);
  const tail = /[^\s]*$/.exec(rest)?.[0] ?? "";
  return { lead: rest.slice(0, rest.length - tail.length), head, tail };
}

const DATE = /(\d{4}-(?:W\d{2}|\d{2}(?:-\d{2})?))/;

/** Keep dates like 2025-01, 2025-01-15 and 2025-W05 on one line: never "2025-" then "01". */
export function keepDates(text: string): ReactNode {
  const pieces = text.split(DATE);
  if (pieces.length === 1) return text;
  return pieces.map((piece, i) =>
    i % 2 ? (
      // biome-ignore lint/suspicious/noArrayIndexKey: pieces of one string, in order
      <span key={i} className={styles.nobreak}>
        {piece}
      </span>
    ) : (
      piece
    ),
  );
}

function Sentence({ sentence, onFact }: { sentence: StorySentence; onFact: (id: string) => void }) {
  const parts = sentence.parts?.length ? sentence.parts : [{ text: sentence.text, fact_id: null }];
  // each text part gives its first word to the number before it and its last to the one after
  const cut = parts.map((p) => (p.fact_id ? null : edges(p.text)));
  return (
    <>
      {parts.map((part, i) => {
        const before = cut[i - 1];
        const after = cut[i + 1];
        if (part.fact_id) {
          return (
            // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list that never reorders
            <span key={i} className={styles.together}>
              {before?.tail}
              <button
                type="button"
                className={styles.number}
                onClick={() => onFact(part.fact_id as string)}
                title="Where this number comes from"
              >
                {part.text}
              </button>
              {after?.head}
            </span>
          );
        }
        const own = cut[i] as { lead: string; head: string; tail: string };
        const head = parts[i - 1]?.fact_id ? "" : own.head;
        const tail = parts[i + 1]?.fact_id ? "" : own.tail;
        // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list that never reorders
        return <span key={i}>{keepDates(head + own.lead + tail)}</span>;
      })}
    </>
  );
}

function FactPanel({ fact, onClose }: { fact: Fact; onClose: () => void }) {
  useEffect(() => {
    const close = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [onClose]);
  return (
    <aside className={styles.panel} aria-label={`Fact ${fact.id}`}>
      <div className={styles.panelHead}>
        <span className={styles.factId}>{fact.id}</span>
        <button type="button" className={styles.close} onClick={onClose} aria-label="Close">
          <Icon name="close" size={16} />
        </button>
      </div>
      <h3 className={styles.factTitle}>{fact.title}</h3>
      <p className={styles.factStatement}>{fact.statement}</p>
      <dl className={styles.factFacts}>
        <div>
          <dt>How it was computed</dt>
          <dd>{fact.method}</dd>
        </div>
        <div>
          <dt>Rows behind it</dt>
          <dd className={styles.factRows}>{fact.n.toLocaleString("en-US")}</dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd className={styles.confidence} data-level={fact.confidence}>
            {fact.confidence}
          </dd>
        </div>
        <div>
          <dt>Checked</dt>
          <dd>
            {fact.checked ? (
              <span className={styles.checked}>
                <Icon name="check" size={14} /> Recomputed in DuckDB from separate SQL: the same
              </span>
            ) : (
              "Not recomputed"
            )}
          </dd>
        </div>
      </dl>
      {fact.caveats.length > 0 && (
        <ul className={styles.caveats}>
          {fact.caveats.map((c) => (
            <li key={c}>{c}</li>
          ))}
        </ul>
      )}
      {(fact.sql || fact.points_sql) && (
        <details className={styles.sql}>
          <summary>The SQL that checked it</summary>
          {fact.sql && <pre>{fact.sql}</pre>}
          {fact.points_sql && <pre>{fact.points_sql}</pre>}
        </details>
      )}
    </aside>
  );
}

function StoryView({ data, onFact }: { data: StorytellerData; onFact: (id: string) => void }) {
  const story = data.story;
  if (!story) return null;
  return (
    <>
      {story.pages.map((page, n) => (
        <Block
          key={page.id}
          level={0}
          label={
            <span className={styles.pageNo}>
              {n + 1} / {story.pages.length}
            </span>
          }
          note={ROLE[page.role]}
        >
          <section className={styles.page} aria-labelledby={`page-${page.id}`}>
            <h2 id={`page-${page.id}`} className={styles.pageTitle}>
              {keepDates(page.title)}
            </h2>
            <p className={styles.headline}>
              <Sentence sentence={page.headline} onFact={onFact} />
            </p>
            {page.charts && page.charts.length > 0 && (
              <div className={styles.charts} data-count={page.charts.length}>
                {page.charts.map((chart) => (
                  <ChartFigure key={`${chart.kind}-${chart.fact_id}`} chart={chart} onFact={onFact} />
                ))}
              </div>
            )}
            {page.body.length > 0 && (
              <ul className={styles.body}>
                {page.body.map((s, i) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list that never reorders
                  <li key={i}>
                    <Sentence sentence={s} onFact={onFact} />
                  </li>
                ))}
              </ul>
            )}
            {page.actions.length > 0 && (
              <ol className={styles.actions}>
                {page.actions.map((a) => (
                  <li key={a.text}>
                    <p className={styles.actionText}>{a.text}</p>
                    <p className={styles.actionCheck}>
                      <b>How to test it:</b> {a.check}
                    </p>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </Block>
      ))}
    </>
  );
}

function Cleaning({ data }: { data: StorytellerData }) {
  const c = data.cleaning;
  return (
    <div className={styles.cleaning}>
      <p className={styles.cleaningLead}>
        {c.rows_in.toLocaleString("en-US")} rows in, {c.rows_out.toLocaleString("en-US")} out; {c.columns_in}{" "}
        columns in, {c.columns_out} out.
      </p>
      {c.steps.length === 0 ? (
        <p className="muted">Nothing needed changing.</p>
      ) : (
        <ul className={styles.steps}>
          {c.steps.map((s) => (
            <li key={s.id}>
              <span className="tag" data-tone={s.decided_by === "default" ? "red" : undefined}>
                {DECIDED[s.decided_by]}
              </span>
              <span>{s.summary}.</span>
              {s.examples.length > 0 && (
                <span className={styles.examples}>
                  {s.examples.slice(0, 3).map((e) => (
                    <code key={`${e.row}-${e.before}`}>
                      row {e.row}: {e.before} → {e.after ?? "empty"}
                    </code>
                  ))}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
      <ul className={styles.checks}>
        {c.check.map((line) => (
          <li key={line}>
            <Icon name="check" size={14} /> {line}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Columns({ data }: { data: StorytellerData }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th scope="col">Column</th>
            <th scope="col">Holds</th>
            <th scope="col">Adds up by</th>
            <th scope="col">Empty</th>
            <th scope="col">Notes</th>
          </tr>
        </thead>
        <tbody>
          {data.columns.map((c) => (
            <tr key={c.name}>
              <th scope="row">
                {c.name}
                {c.personal && (
                  <span className={`tag ${styles.personal}`} data-tone="red">
                    personal
                  </span>
                )}
              </th>
              <td>
                {c.type}, {c.role.replace("_", " ")}
              </td>
              <td>{c.aggregation.replace("_", " ")}</td>
              <td>{c.missing.toLocaleString("en-US")}</td>
              <td className={styles.colNotes}>{c.notes.join(" ") || c.reason}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function StorytellerResult({ run, result }: ResultViewProps) {
  const data = useMemo(() => asStorytellerData(result.data), [result.data]);
  const [open, setOpen] = useState<string | null>(null);
  const facts = useMemo(() => new Map((data?.facts?.facts ?? []).map((f) => [f.id, f] as const)), [data]);
  if (!data?.story) return <GenericResult run={run} result={result} />;
  const story = data.story;
  const fact = open ? facts.get(open) : undefined;
  const checked = data.facts?.facts.filter((f) => f.checked).length ?? 0;

  return (
    <ResultLayout>
      <StatusBanner result={result} />
      <Block
        label="The story"
        level={0}
        note={
          <>
            <p>in {data.source.file}</p>
            <p>
              {story.written_by === "model"
                ? `Written by ${story.model ?? "a model"}${story.attempts > 1 ? ` in ${story.attempts} drafts` : ""}`
                : "Written from a template"}
            </p>
            <p>{checked} facts, each computed twice</p>
          </>
        }
      >
        <header className={styles.storyHead}>
          <h1 className={styles.storyTitle}>{story.title}</h1>
          <p className={styles.hint}>
            Every <span className={styles.numberSample}>underlined number</span> opens the fact behind it.
          </p>
          {story.context && (
            <p className={styles.context}>
              <b>Your context:</b> {story.context}
            </p>
          )}
          <ExportButtons run={run} result={result} />
        </header>
      </Block>

      <StoryView data={data} onFact={setOpen} />

      <Section title="Cleaning" count={data.cleaning.steps.length} note="Every change made to the data">
        <Cleaning data={data} />
      </Section>
      <Section title="Columns" count={data.columns.length}>
        <Columns data={data} />
      </Section>
      {story.rejected.length > 0 && (
        <Section title="Refused drafts" count={story.rejected.length} note="What the checks turned down">
          <ul className={styles.refused}>
            {story.rejected.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </Section>
      )}
      <ResultFooter result={result} />
      {fact && <FactPanel fact={fact} onClose={() => setOpen(null)} />}
    </ResultLayout>
  );
}
