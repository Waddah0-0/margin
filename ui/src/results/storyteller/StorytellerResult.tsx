/**
 * The Data Storyteller's own result view: the story page by page, with its charts, and
 * every number a button that opens the fact behind it (how it was computed, on how many
 * rows, how sure it is, and that DuckDB got the same number). Below the story: how the
 * data was cleaned and what each column holds. A run without a story (cleaning only)
 * uses the generic viewer.
 */
import { useEffect, useMemo, useState } from "react";
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

/** Split off the punctuation touching a number ("(", ", "), so it wraps with the number. */
function edges(text: string): { lead: string; head: string; tail: string } {
  const head = /^[^\s]*/.exec(text)?.[0] ?? "";
  const rest = text.slice(head.length);
  const tail = /[^\s]*$/.exec(rest)?.[0] ?? "";
  return { lead: rest.slice(0, rest.length - tail.length), head, tail };
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
        return <span key={i}>{head + own.lead + tail}</span>;
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
          <Icon name="close" size={20} />
        </button>
      </div>
      <h3 className="title-m">{fact.title}</h3>
      <p className="body-l">{fact.statement}</p>
      <dl className={styles.factFacts}>
        <div>
          <dt>How it was computed</dt>
          <dd>{fact.method}</dd>
        </div>
        <div>
          <dt>Rows behind it</dt>
          <dd>{fact.n.toLocaleString("en-US")}</dd>
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
                <Icon name="checkCircle" size={16} /> Recomputed in DuckDB from separate SQL: the same
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
            <li key={c}>
              <Icon name="warning" size={16} /> {c}
            </li>
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
    <div className={styles.pages}>
      {story.pages.map((page, n) => (
        <section key={page.id} className={styles.page} aria-labelledby={`page-${page.id}`}>
          <p className={`label-l ${styles.pageNo}`}>
            {n + 1} / {story.pages.length}
          </p>
          <h2 id={`page-${page.id}`} className={styles.pageTitle}>
            {page.title}
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
                  <p className="title-m">{a.text}</p>
                  <p className="body-m muted">
                    <b>How to test it:</b> {a.check}
                  </p>
                </li>
              ))}
            </ol>
          )}
        </section>
      ))}
    </div>
  );
}

function Cleaning({ data }: { data: StorytellerData }) {
  const c = data.cleaning;
  return (
    <div className={styles.cleaning}>
      <p className="body-l">
        {c.rows_in.toLocaleString("en-US")} rows in, {c.rows_out.toLocaleString("en-US")} out; {c.columns_in}{" "}
        columns in, {c.columns_out} out.
      </p>
      {c.steps.length === 0 ? (
        <p className="body-m muted">Nothing needed changing.</p>
      ) : (
        <ul className={styles.steps}>
          {c.steps.map((s) => (
            <li key={s.id}>
              <span className={styles.decided} data-by={s.decided_by}>
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
            <Icon name="checkCircle" size={16} /> {line}
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
                {c.personal && <span className={styles.personal}>personal</span>}
              </th>
              <td>
                {c.type}, {c.role.replace("_", " ")}
              </td>
              <td>{c.aggregation.replace("_", " ")}</td>
              <td>{c.missing.toLocaleString("en-US")}</td>
              <td className="body-s muted">{c.notes.join(" ") || c.reason}</td>
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
      <header className={styles.storyHead}>
        <p className="label-l muted">The story in {data.source.file}</p>
        <h1 className={styles.storyTitle}>{story.title}</h1>
        <div className={styles.chips}>
          <span className={styles.chip}>
            <Icon name="model" size={16} />
            {story.written_by === "model"
              ? `Written by ${story.model ?? "a model"}${story.attempts > 1 ? ` in ${story.attempts} drafts` : ""}`
              : "Written from a template"}
          </span>
          <span className={styles.chip}>
            <Icon name="checkCircle" size={16} />
            {checked} facts, each computed twice
          </span>
          <span className={styles.chip}>
            <Icon name="info" size={16} />
            Click any number to see where it comes from
          </span>
        </div>
        {story.context && (
          <p className="body-m muted">
            <b>Your context:</b> {story.context}
          </p>
        )}
        <ExportButtons run={run} result={result} />
      </header>

      <StoryView data={data} onFact={setOpen} />

      <Section title="How the data was cleaned" count={data.cleaning.steps.length}>
        <Cleaning data={data} />
      </Section>
      <Section title="The columns" count={data.columns.length}>
        <Columns data={data} />
      </Section>
      {story.rejected.length > 0 && (
        <Section title="What the checks refused" count={story.rejected.length}>
          <ul className={styles.refused}>
            {story.rejected.map((r) => (
              <li key={r} className="body-s">
                {r}
              </li>
            ))}
          </ul>
        </Section>
      )}
      <ResultFooter result={result} />
      {fact && <FactPanel fact={fact} onClose={() => setOpen(null)} />}
    </ResultLayout>
  );
}
