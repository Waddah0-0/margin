import type { CSSProperties, ReactNode } from "react";
import type { AgentResult, Answer, Evidence, Finding, RunView } from "../api/client";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import type { IconName } from "../components/icons";
import { download, duration } from "../lib/format";
import styles from "./GenericResult.module.css";
import { JsonTree } from "./JsonTree";
import { toMarkdown } from "./markdown";
import type { ResultViewProps } from "./registry";

/*
 * The generic viewer is built from pieces that custom views reuse: the status banner, the
 * export buttons, finding cards, warnings, run details and the raw JSON.
 */

function ScoreMeter({ value }: { value: number }) {
  const unit = value >= 0 && value <= 1;
  return (
    <span className={styles.score} title={`Score ${value}`}>
      {unit && (
        <span className={styles.meter} style={{ "--v": value } as CSSProperties}>
          <span />
        </span>
      )}
      <span className={styles.scoreText}>{unit ? value.toFixed(2) : value}</span>
    </span>
  );
}

/** A weight in [-1, 1] as a bar growing left (against) or right (for) from the centre. */
export function WeightBar({ weight }: { weight: number }) {
  const clamped = Math.max(-1, Math.min(1, weight));
  return (
    <span
      className={styles.weight}
      data-sign={clamped >= 0 ? "pos" : "neg"}
      style={{ "--w": Math.abs(clamped) } as CSSProperties}
      title={`Weight ${weight >= 0 ? "+" : ""}${weight.toFixed(2)}`}
    >
      <span className={styles.weightBar} />
      <span className={styles.weightText}>
        {weight >= 0 ? "+" : "−"}
        {Math.abs(weight).toFixed(2)}
      </span>
    </span>
  );
}

export function EvidenceRow({ evidence }: { evidence: Evidence }) {
  return (
    <li className={styles.evidence}>
      <span className={styles.kind}>{evidence.kind}</span>
      <div className={styles.evidenceBody}>
        {evidence.location && <code className={styles.location}>{evidence.location}</code>}
        <p>{evidence.detail}</p>
      </div>
      {evidence.weight !== null && evidence.weight !== undefined && <WeightBar weight={evidence.weight} />}
    </li>
  );
}

export function FindingCard({ finding, open }: { finding: Finding; open: boolean }) {
  const evidence = finding.evidence ?? [];
  return (
    <details className={styles.finding} open={open || undefined}>
      <summary className={styles.findingHead}>
        <div className={styles.findingTitle}>
          <h3 className="title-m">{finding.title}</h3>
          <p className="body-m muted">{finding.summary}</p>
        </div>
        {finding.severity_or_score !== null && finding.severity_or_score !== undefined && (
          <ScoreMeter value={finding.severity_or_score} />
        )}
        {evidence.length > 0 && (
          <span className={styles.evidenceCount}>
            {evidence.length} {evidence.length === 1 ? "piece" : "pieces"} of evidence
            <Icon name="expand" className={styles.chevron} />
          </span>
        )}
      </summary>
      {evidence.length > 0 && (
        <ul className={styles.evidenceList}>
          {evidence.map((ev, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list that never reorders
            <EvidenceRow key={`${ev.kind}-${ev.location}-${i}`} evidence={ev} />
          ))}
        </ul>
      )}
    </details>
  );
}

const BANNER = {
  partial: {
    icon: "warning",
    title: "Partial result",
    text: "Some of the work was skipped. The warnings below say what.",
  },
  error: { icon: "error", title: "The run failed", text: "" },
} as const;

export function StatusBanner({ result }: { result: AgentResult }) {
  if (result.status === "ok") return null;
  const banner = BANNER[result.status];
  return (
    <div className={styles.banner} data-status={result.status} role="status">
      <Icon name={banner.icon} />
      <div>
        <p className="title-m">{banner.title}</p>
        <p className="body-m">{result.status === "error" ? result.error : banner.text}</p>
      </div>
    </div>
  );
}

export function ExportButtons({ run, result }: { run: RunView; result: AgentResult }) {
  const base = `${result.agent_id}-${run.run_id.slice(0, 8)}`;
  return (
    <div className={styles.exports}>
      <Button
        variant="outlined"
        size="s"
        icon="download"
        onClick={() => download(`${base}.json`, `${JSON.stringify(result, null, 2)}\n`, "application/json")}
      >
        JSON
      </Button>
      <Button
        variant="outlined"
        size="s"
        icon="download"
        onClick={() => download(`${base}.md`, toMarkdown(result), "text/markdown")}
      >
        Markdown
      </Button>
      <Button
        variant="text"
        size="s"
        icon="copy"
        onClick={() => navigator.clipboard?.writeText(toMarkdown(result))}
      >
        Copy as Markdown
      </Button>
    </div>
  );
}

export function Section({
  title,
  count,
  children,
  aside,
}: {
  title: string;
  count?: number;
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <section className={styles.section}>
      <div className={styles.sectionHeadRow}>
        <h2 className={styles.sectionTitle}>
          {title} {count !== undefined && <span className={styles.badge}>{count}</span>}
        </h2>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function FindingList({ findings }: { findings: Finding[] }) {
  return (
    <div className={styles.findings}>
      {findings.map((f, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list that never reorders
        <FindingCard key={`${f.title}-${i}`} finding={f} open={findings.length <= 2} />
      ))}
    </div>
  );
}

export function WarningList({ warnings }: { warnings: string[] }) {
  return (
    <ul className={styles.warnings}>
      {warnings.map((w, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list that never reorders
        <li key={`${i}-${w}`}>
          <Icon name="info" size={20} />
          <span>{w}</span>
        </li>
      ))}
    </ul>
  );
}

export function RunDetails({ result }: { result: AgentResult }) {
  const meta = result.metadata;
  const usage = meta?.usage;
  const details: [IconName, string, string][] = [];
  if (meta?.duration_s !== null && meta?.duration_s !== undefined)
    details.push(["timer", "Duration", duration(meta.duration_s)]);
  if (meta?.model) details.push(["model", "Model", meta.model]);
  if (usage?.llm_calls) {
    details.push(["modelCalls", "Model calls", String(usage.llm_calls)]);
    details.push(["tokens", "Tokens in / out", `${usage.input_tokens} / ${usage.output_tokens}`]);
    if (usage.cost_usd) details.push(["cost", "Estimated cost", `$${usage.cost_usd.toFixed(4)}`]);
  }
  details.push(["package", "Agent version", result.agent_version]);
  return (
    <dl className={styles.details}>
      {details.map(([icon, label, value]) => (
        <div key={label} className={styles.detail}>
          <Icon name={icon} className={styles.detailIcon} />
          <dt className="body-s muted">{label}</dt>
          <dd className="title-m">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function RawResult({ result }: { result: AgentResult }) {
  return (
    <section className={styles.section}>
      <details className={styles.raw}>
        <summary className={styles.rawHead}>
          <Icon name="code" />
          <span className="title-m">Raw result</span>
          <span className="body-m muted">Everything the agent returned, as JSON</span>
          <Icon name="expand" className={styles.chevron} />
        </summary>
        <div className={styles.rawBody}>
          <JsonTree value={result} openDepth={1} />
        </div>
      </details>
    </section>
  );
}

export const ANSWERED_BY: Record<Answer["source"], string> = {
  user: "You",
  preset: "The run's input",
  default: "Default, not confirmed",
};

/** The questions the agent asked during the run, and how each was answered. */
export function AnswerList({ answers }: { answers: Answer[] }) {
  return (
    <ul className={styles.answers}>
      {answers.map((a) => (
        <li key={a.question_id} className={styles.answer}>
          <span className="body-m muted">{a.prompt}</span>
          <span className="title-m">{a.label}</span>
          <span className={styles.answeredBy} data-source={a.source}>
            {ANSWERED_BY[a.source]}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** The closing sections every view ends with: warnings, answers, run details, raw JSON. */
export function ResultFooter({ result }: { result: AgentResult }) {
  const warnings = result.warnings ?? [];
  const answers = result.metadata?.answers ?? [];
  return (
    <>
      {warnings.length > 0 && (
        <Section title="Warnings" count={warnings.length}>
          <WarningList warnings={warnings} />
        </Section>
      )}
      {answers.length > 0 && (
        <Section title="Answers" count={answers.length}>
          <AnswerList answers={answers} />
        </Section>
      )}
      <Section title="Run details">
        <RunDetails result={result} />
      </Section>
      <RawResult result={result} />
    </>
  );
}

export function ResultLayout({ children }: { children: ReactNode }) {
  return <div className={styles.result}>{children}</div>;
}

/** The viewer every agent gets: summary, findings with evidence, warnings, metadata, raw data. */
export function GenericResult({ run, result }: ResultViewProps) {
  const findings = result.findings ?? [];
  return (
    <ResultLayout>
      <StatusBanner result={result} />
      <section className={styles.summary}>
        <p className="label-l muted">Summary</p>
        <p className={`headline-s ${styles.summaryText}`}>{result.summary}</p>
        <ExportButtons run={run} result={result} />
      </section>
      {findings.length > 0 && (
        <Section title="Findings" count={findings.length}>
          <FindingList findings={findings} />
        </Section>
      )}
      <ResultFooter result={result} />
    </ResultLayout>
  );
}
