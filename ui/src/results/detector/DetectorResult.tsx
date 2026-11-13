/**
 * The AI Code Detector's own result view: the estimate with its range and confidence, the
 * evidence for and against side by side, the files with their code and marked lines, and
 * the commit history. Falls back to the generic viewer when the data isn't the detector's.
 */
import { type CSSProperties, type ReactNode, useMemo, useRef, useState } from "react";
import { Block } from "../../components/Block";
import {
  ExportButtons,
  FindingList,
  GenericResult,
  ResultFooter,
  ResultLayout,
  Section,
  StatusBanner,
} from "../GenericResult";
import type { ResultViewProps } from "../registry";
import { CommitTimeline } from "./CommitTimeline";
import styles from "./detector.module.css";
import { FilesExplorer, type Selection } from "./FilesExplorer";
import { collectEvidence, type EvidenceEntry, SHOWN_ELSEWHERE } from "./logic";
import { asDetectorData, type DetectorData } from "./types";

const CONFIDENCE_STEPS = { low: 1, medium: 2, high: 3 } as const;

function EstimateHeader({ data, children }: { data: DetectorData; children: ReactNode }) {
  const [low, high] = data.estimate_range;
  const confidence = data.confidence;
  return (
    <Block
      label="Estimate"
      note={
        data.methodology_version ? (
          <span className={styles.methodology}>{data.methodology_version}</span>
        ) : undefined
      }
    >
      <div className={styles.header}>
        <div className={styles.estimate}>
          <p className={styles.caption}>Estimated likelihood of AI assistance</p>
          <p className={styles.bigNumber}>{data.estimate.toFixed(2)}</p>
          <p className={styles.range}>
            plausibly between <b>{low.toFixed(2)}</b> and <b>{high.toFixed(2)}</b>
          </p>
          <div
            className={styles.scale}
            style={{ "--low": low, "--high": high, "--value": data.estimate } as CSSProperties}
            role="img"
            aria-label={`Estimate ${data.estimate.toFixed(2)} on a scale from 0 to 1, range ${low.toFixed(2)} to ${high.toFixed(2)}`}
          >
            <span className={styles.scaleRange} />
            <span className={styles.scaleValue} />
          </div>
          <div className={styles.scaleLabels}>
            <span data-side="against">0 · reads like people wrote it</span>
            <span data-side="for">reads like AI wrote it · 1</span>
          </div>
        </div>

        <div className={styles.confidence}>
          <div className={styles.confidenceHead}>
            <span className={styles.steps} aria-hidden="true">
              {[1, 2, 3].map((n) => (
                <span key={n} data-on={n <= CONFIDENCE_STEPS[confidence]} />
              ))}
            </span>
            <span>{confidence.charAt(0).toUpperCase() + confidence.slice(1)} confidence</span>
          </div>
          {data.confidence_reasons.length > 0 && (
            <ul className={styles.reasons}>
              {data.confidence_reasons.map((r) => (
                <li key={r}>{r.charAt(0).toUpperCase() + r.slice(1)}.</li>
              ))}
            </ul>
          )}
          <dl className={styles.stats}>
            <div>
              <dt>Files scored</dt>
              <dd>{data.files_analyzed}</dd>
            </div>
            <div>
              <dt>Not scored</dt>
              <dd>{data.files_skipped}</dd>
            </div>
            <div>
              <dt>Commits</dt>
              <dd>{data.commits_total}</dd>
            </div>
          </dl>
        </div>
      </div>

      <p className={styles.caveat}>
        This is an estimate, not proof. Clean human code can look machine-made, and edited AI code can look
        human. Use it to start a conversation, never as the only basis for accusing anyone.
      </p>
      {children}
    </Block>
  );
}

function Markers({ data }: { data: DetectorData }) {
  if (!data.metadata_markers.length) return null;
  const tools = [...new Set(data.metadata_markers.map((m) => m.tool))];
  return (
    <Block label="Metadata" note="Reported, never scored">
      <div className={styles.markers}>
        <p className={styles.markersLead}>The repository's own metadata names AI tools: {tools.join(", ")}</p>
        <p className={styles.markersWhy}>
          This proves the tools were used, not how much of the code they wrote, so it is not part of the
          estimate.
        </p>
        <ul className={styles.markerList}>
          {data.metadata_markers.map((m) => (
            <li key={`${m.kind}-${m.tool}-${m.location}`}>
              <span className="tag">{m.tool}</span>
              <span>{m.detail}</span>
              <code>{m.kind === "config_file" ? m.location : m.location.slice(0, 10)}</code>
            </li>
          ))}
        </ul>
      </div>
    </Block>
  );
}

const COLUMN_PREVIEW = 6;

function EvidenceColumn({
  side,
  entries,
  onPick,
}: {
  side: "for" | "against";
  entries: EvidenceEntry[];
  onPick: (entry: EvidenceEntry) => void;
}) {
  const [all, setAll] = useState(false);
  const shown = all ? entries : entries.slice(0, COLUMN_PREVIEW);
  return (
    <div className={styles.column} data-side={side}>
      <h3 className={styles.columnTitle}>
        {side === "for" ? "Toward AI" : "Toward a human"}
        <span className={styles.columnCount}>{entries.length}</span>
      </h3>
      {entries.length === 0 ? (
        <p className={styles.columnEmpty}>Nothing pointed this way.</p>
      ) : (
        <ul className={styles.entries}>
          {shown.map((e, i) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: a fixed list that never reorders
            <li key={i}>
              <button
                type="button"
                className={styles.entry}
                onClick={() => onPick(e)}
                disabled={!e.path}
                title={e.path ? "Show this in the file" : undefined}
              >
                <span className={styles.entryText}>{e.text.charAt(0).toUpperCase() + e.text.slice(1)}</span>
                {e.quote && <code className={styles.entryQuote}>{e.quote}</code>}
                <span className={styles.entryMeta}>
                  <span className={styles.entrySource}>{e.source === "judge" ? "model" : "signal"}</span>
                  {e.location && <code>{e.location}</code>}
                  {e.weight !== undefined && (
                    <span className={styles.entryWeight}>
                      {e.weight >= 0 ? "+" : "−"}
                      {Math.abs(e.weight).toFixed(2)}
                    </span>
                  )}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {entries.length > COLUMN_PREVIEW && (
        <button type="button" className={`link ${styles.more}`} onClick={() => setAll(!all)}>
          {all ? "Show fewer" : `Show all ${entries.length}`}
        </button>
      )}
    </div>
  );
}

function DetectorView({ run, result, data }: ResultViewProps & { data: DetectorData }) {
  const findings = result.findings ?? [];
  const evidence = useMemo(() => collectEvidence(data, findings), [data, findings]);
  const rest = findings.filter((f) => !SHOWN_ELSEWHERE.has(f.title));
  const filesRef = useRef<HTMLDivElement>(null);
  const [selection, setSelection] = useState<Selection | null>(null);

  const pick = (entry: EvidenceEntry) => {
    if (!entry.path) return;
    setSelection({ path: entry.path, line: entry.line, at: Date.now() });
    filesRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  return (
    <ResultLayout>
      <StatusBanner result={result} />
      <EstimateHeader data={data}>
        <ExportButtons run={run} result={result} />
      </EstimateHeader>
      <Markers data={data} />

      <Section title="Evidence" note="For and against, side by side. Pick one to see it in its file.">
        <div className={styles.columns}>
          <EvidenceColumn side="for" entries={evidence.for} onPick={pick} />
          <EvidenceColumn side="against" entries={evidence.against} onPick={pick} />
        </div>
      </Section>

      <div ref={filesRef} className={styles.anchor}>
        <Section title="Files" count={data.files.length}>
          <FilesExplorer data={data} selection={selection} onSelect={setSelection} />
        </Section>
      </div>

      {data.commits.length > 0 && (
        <Section title="History" count={data.commits_total} note="Authors are left out on purpose">
          <CommitTimeline commits={data.commits} total={data.commits_total} />
        </Section>
      )}

      {rest.length > 0 && (
        <Section title="Also in the report">
          <FindingList findings={rest} />
        </Section>
      )}

      <ResultFooter result={result} />
    </ResultLayout>
  );
}

export function DetectorResult(props: ResultViewProps) {
  const data = props.result.status === "error" ? null : asDetectorData(props.result.data);
  if (!data) return <GenericResult {...props} />;
  return <DetectorView {...props} data={data} />;
}
