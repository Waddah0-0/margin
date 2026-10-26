import { type FormEvent, useId, useState } from "react";
import { api, call, type Question, type QuestionBatch } from "../api/client";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { EvidenceRow } from "../results/GenericResult";
import resultStyles from "../results/GenericResult.module.css";
import fieldStyles from "./Fields.module.css";
import styles from "./QuestionForm.module.css";

type Value = string | number | boolean;

/** What one question's inputs hold while the person decides. */
interface Draft {
  picked: Value | null; // choice
  other: boolean; // choice with allow_other: "Other" is picked
  otherText: string;
  many: Value[]; // multi_choice
  text: string; // text
}

const choicesOf = (q: Question) => q.choices ?? [];
const isChoice = (q: Question, v: unknown) => choicesOf(q).some((c) => c.value === v);

function draftFor(q: Question): Draft {
  const d = q.default;
  const kind = q.kind ?? "choice";
  const draft: Draft = { picked: null, other: false, otherText: "", many: [], text: "" };
  if (kind === "multi_choice") draft.many = Array.isArray(d) ? (d as Value[]) : [];
  else if (kind === "text") draft.text = typeof d === "string" ? d : "";
  else if (d !== null && d !== undefined) {
    if (isChoice(q, d)) draft.picked = d as Value;
    else if (q.allow_other) Object.assign(draft, { other: true, otherText: String(d) });
  }
  return draft;
}

/** The answer to send, or an error message when a required question is left empty. */
function answerOf(q: Question, draft: Draft): { value: unknown; error?: string } {
  const required = q.required ?? true;
  switch (q.kind ?? "choice") {
    case "multi_choice":
      return { value: draft.many, error: required && !draft.many.length ? "Pick at least one" : undefined };
    case "text": {
      const text = draft.text.trim();
      return { value: text || null, error: required && !text ? "An answer is required" : undefined };
    }
    default: {
      const value = draft.other ? draft.otherText.trim() || null : draft.picked;
      return { value, error: required && value === null ? "Choose one" : undefined };
    }
  }
}

function sections(questions: Question[]): [string | null, Question[]][] {
  const groups: [string | null, Question[]][] = [];
  for (const q of questions) {
    const name = q.section ?? null;
    const last = groups[groups.length - 1];
    if (last && last[0] === name) last[1].push(q);
    else groups.push([name, [q]]);
  }
  return groups;
}

function QuestionField({
  question,
  draft,
  error,
  onChange,
}: {
  question: Question;
  draft: Draft;
  error?: string;
  onChange: (draft: Draft) => void;
}) {
  const name = useId();
  const kind = question.kind ?? "choice";
  const evidence = question.evidence ?? [];
  const suggested = (v: Value) =>
    Array.isArray(question.default) ? question.default.includes(v) : question.default === v;

  return (
    <fieldset className={styles.question} aria-describedby={error ? `${name}-error` : undefined}>
      <legend className={`title-m ${styles.prompt}`}>{question.prompt}</legend>
      {question.detail && <p className="body-m muted">{question.detail}</p>}
      {evidence.length > 0 && (
        <ul className={`${resultStyles.evidenceList} ${styles.evidence}`}>
          {evidence.map((ev, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list that never reorders
            <EvidenceRow key={i} evidence={ev} />
          ))}
        </ul>
      )}

      {kind === "text" ? (
        <label className={fieldStyles.outlined} data-error={Boolean(error)} data-multiline="true">
          <textarea
            className={fieldStyles.input}
            aria-label={question.prompt}
            value={draft.text}
            rows={3}
            onChange={(e) => onChange({ ...draft, text: e.target.value })}
          />
        </label>
      ) : (
        <div className={styles.options}>
          {choicesOf(question).map((choice) => {
            const multi = kind === "multi_choice";
            const checked = multi
              ? draft.many.includes(choice.value)
              : !draft.other && draft.picked === choice.value;
            return (
              <label key={String(choice.value)} className={styles.option} data-checked={checked}>
                <input
                  type={multi ? "checkbox" : "radio"}
                  name={name}
                  checked={checked}
                  onChange={() =>
                    onChange(
                      multi
                        ? {
                            ...draft,
                            many: checked
                              ? draft.many.filter((v) => v !== choice.value)
                              : [...draft.many, choice.value],
                          }
                        : { ...draft, picked: choice.value, other: false },
                    )
                  }
                />
                <span className={styles.optionText}>
                  <span className={styles.optionLabel}>
                    {choice.label}
                    {suggested(choice.value) && <span className={styles.suggested}>Suggested</span>}
                  </span>
                  {choice.detail && <span className="body-m muted">{choice.detail}</span>}
                </span>
              </label>
            );
          })}
          {question.allow_other && (
            <label className={styles.option} data-checked={draft.other}>
              <input
                type="radio"
                name={name}
                checked={draft.other}
                onChange={() => onChange({ ...draft, other: true })}
              />
              <span className={styles.optionText}>
                <span className={styles.optionLabel}>Something else</span>
                <input
                  className={styles.otherInput}
                  aria-label={`${question.prompt} (your own answer)`}
                  value={draft.otherText}
                  placeholder="Type your answer"
                  onFocus={() => !draft.other && onChange({ ...draft, other: true })}
                  onChange={(e) => onChange({ ...draft, other: true, otherText: e.target.value })}
                />
              </span>
            </label>
          )}
        </div>
      )}
      {error && (
        <p id={`${name}-error`} className={fieldStyles.support} data-error="true">
          <Icon name="error" size={16} />
          {error}
        </p>
      )}
    </fieldset>
  );
}

/**
 * The questions a waiting run asked. Defaults are filled in as suggestions; sending the
 * answers lets the run carry on (the page follows it through the run's events).
 */
export function QuestionForm({ runId, batch }: { runId: string; batch: QuestionBatch }) {
  const [drafts, setDrafts] = useState<Record<string, Draft>>(() =>
    Object.fromEntries(batch.questions.map((q) => [q.id, draftFor(q)])),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [sending, setSending] = useState(false);
  const [failure, setFailure] = useState<string>();

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const answers: Record<string, unknown> = {};
    const found: Record<string, string> = {};
    for (const q of batch.questions) {
      const { value, error } = answerOf(q, drafts[q.id] ?? draftFor(q));
      answers[q.id] = value;
      if (error) found[q.id] = error;
    }
    setErrors(found);
    if (Object.keys(found).length) return;
    setSending(true);
    setFailure(undefined);
    try {
      await call(
        api.POST("/runs/{run_id}/answers", {
          params: { path: { run_id: runId } },
          body: { batch: batch.id ?? "", answers },
        }),
      );
    } catch (err) {
      setFailure((err as Error).message);
      setSending(false);
    }
  };

  return (
    <form className={styles.card} onSubmit={submit} aria-labelledby="questions-title">
      <div className={styles.head}>
        <p className={`label-l ${styles.eyebrow}`}>
          <Icon name="question" size={18} />
          The agent is asking
        </p>
        <h2 id="questions-title" className="headline-s">
          {batch.title}
        </h2>
        {batch.detail && <p className="body-m muted">{batch.detail}</p>}
      </div>

      {sections(batch.questions).map(([section, questions]) => (
        <div key={section ?? "_"} className={styles.section}>
          {section && <h3 className={styles.sectionTitle}>{section}</h3>}
          {questions.map((q) => (
            <QuestionField
              key={q.id}
              question={q}
              draft={drafts[q.id] ?? draftFor(q)}
              error={errors[q.id]}
              onChange={(draft) => setDrafts((d) => ({ ...d, [q.id]: draft }))}
            />
          ))}
        </div>
      ))}

      <div className={styles.actions}>
        <Button type="submit" icon="forward" disabled={sending}>
          {sending ? "Sending" : "Continue"}
        </Button>
        <span className="body-m muted">Your answers are kept with the result.</span>
        {failure && (
          <span className="body-m" role="alert" style={{ color: "var(--error)" }}>
            {failure}
          </span>
        )}
      </div>
    </form>
  );
}
