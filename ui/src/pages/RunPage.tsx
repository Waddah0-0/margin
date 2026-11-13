import { Suspense, useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { api, call, isFinished, type ProgressEvent, type RunView } from "../api/client";
import { useAgents, useLiveRun } from "../api/hooks";
import { PROVIDER_NAME, type ProviderId } from "../api/settings";
import { ListHead } from "../components/Block";
import { Button, LinkButton } from "../components/Button";
import { CopyButton } from "../components/CopyButton";
import { Icon } from "../components/Icon";
import { PageLoading } from "../components/Loading";
import { Progress } from "../components/Progress";
import { EmptyState, ErrorState } from "../components/States";
import { StatusChip } from "../components/StatusChip";
import { QuestionForm } from "../form/QuestionForm";
import { fieldsFromSchema, valuesFromInput } from "../form/schema";
import { duration, ordinal, secondsBetween, shortId } from "../lib/format";
import { usePageTitle } from "../lib/title";
import { resultViewFor } from "../results/registry";
import styles from "./pages.module.css";

function useNow(active: boolean): number {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

function clock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

/** What the top of a live run says. `said` marks words that are the agent's own. */
function headline(run: RunView, cancelling: boolean): { title: string; detail?: string; said?: boolean } {
  switch (run.status) {
    case "queued":
      return {
        title: "Waiting for its turn",
        detail: run.queue_position
          ? `${ordinal(run.queue_position)} in line. Agents that use a model run one at a time.`
          : undefined,
      };
    case "waiting":
      return {
        title: cancelling ? "Stopping…" : "Waiting for your answer",
        detail: "The agent paused to ask you something. It carries on once you answer.",
      };
    default:
      if (cancelling)
        return {
          title: "Stopping…",
          detail: "The agent stops at its next checkpoint; a model call in progress finishes first.",
        };
      return run.progress?.message ? { title: run.progress.message, said: true } : { title: "Starting" };
  }
}

/** What the tab says, so a run can be left in the background: where it stands, then whose. */
function tabTitle(run: RunView | undefined, name: string | undefined): string | null {
  if (!run) return null;
  const who = name ?? run.agent_id;
  const fraction = run.progress?.fraction;
  const state =
    run.status === "queued"
      ? "Queued"
      : run.status === "waiting"
        ? "Needs your answer"
        : run.status === "running"
          ? fraction != null
            ? `${Math.round(fraction * 100)}%`
            : "Running"
          : run.status === "cancelled"
            ? "Cancelled"
            : run.result?.status === "error"
              ? "Failed"
              : "Done";
  return `${state} · ${who}`;
}

interface Stage {
  name: string;
  at: number; // when it first appeared, ms
  message: string; // the last thing the agent said during it
}

/** Stages in the order they first appeared, each with the last message it reported. */
export function stagesOf(timeline: ProgressEvent[]): Stage[] {
  const stages: Stage[] = [];
  for (const event of timeline) {
    if (event.stage === "done") continue;
    const known = stages.find((s) => s.name === event.stage);
    if (known) known.message = event.message || known.message;
    else stages.push({ name: event.stage, at: Date.parse(event.timestamp ?? ""), message: event.message });
  }
  return stages;
}

const humanStage = (stage: string) => stage.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());

function offset(ms: number): string {
  if (!Number.isFinite(ms)) return "";
  const s = Math.max(0, ms / 1000);
  return s < 60 ? `+${s.toFixed(1)} s` : `+${clock(s)}`;
}

/**
 * The run's log: one line per stage, with how far into the run it began in the margin.
 * Open while the run is going; folded once there is a result to read instead.
 */
function RunLog({ run, timeline, working }: { run: RunView; timeline: ProgressEvent[]; working: boolean }) {
  const live = !isFinished(run.status);
  const [open, setOpen] = useState(live);
  useEffect(() => setOpen(live), [live]);
  const stages = stagesOf(timeline);
  if (!stages.length) return null;
  const start = Date.parse(run.started_at ?? "") || stages[0]?.at || 0;
  const end = run.finished_at ? Date.parse(run.finished_at) : undefined;

  return (
    <section className={styles.section}>
      <ListHead label="Log" count={stages.length}>
        {!live && (
          <button type="button" className="link" onClick={() => setOpen(!open)} aria-expanded={open}>
            {open ? "Hide the stages" : "Show the stages"}
          </button>
        )}
      </ListHead>
      {open && (
        <ol className={styles.log} aria-label="Stages">
          {stages.map((stage, i) => {
            const current = working && i === stages.length - 1;
            const until = stages[i + 1]?.at ?? end;
            return (
              <li key={stage.name} className={`m-grid ${styles.logRow}`} data-current={current}>
                <span className={`m-note ${styles.logAt}`}>{offset(stage.at - start)}</span>
                <span className={styles.logBody}>
                  <Icon name={current ? "spinner" : "check"} size={14} className={styles.logMark} />
                  <span className={styles.logStage}>{humanStage(stage.name)}</span>
                  <span className={styles.logMessage}>{stage.message}</span>
                  {until !== undefined && !current && (
                    <span className={styles.logTook}>{duration((until - stage.at) / 1000)}</span>
                  )}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

export function RunPage() {
  const { runId = "" } = useParams();
  const { run, timeline, error, missing } = useLiveRun(runId);
  const agents = useAgents();
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string>();
  const live = run ? !isFinished(run.status) : false;
  const working = live && run?.status !== "waiting";
  const now = useNow(live);
  const agent = agents.data?.agents.find((a) => a.id === run?.agent_id);
  usePageTitle(missing ? "Run expired" : tabTitle(run, agent?.name));

  if (missing) {
    return (
      <EmptyState
        label="Expired"
        title="This run is no longer here"
        action={
          <LinkButton variant="outlined" to="/runs" icon="history">
            Recent runs
          </LinkButton>
        }
      >
        <p>Runs are kept in memory for an hour, and are lost when the API restarts.</p>
      </EmptyState>
    );
  }
  if (error && !run) return <ErrorState error={error} onRetry={() => window.location.reload()} />;
  if (!run) return <PageLoading label="Loading run" />;

  const name = agent?.name ?? run.agent_id;
  // the same input again, on the agent's form, to run as it was or change first
  const again =
    agent && run.input && Object.keys(run.input).length
      ? valuesFromInput(fieldsFromSchema(agent.input_schema, agent.primary_input), run.input)
      : undefined;
  const stopping = cancelling && (run.status === "running" || run.status === "waiting");
  const { title, detail, said } = live ? headline(run, stopping) : { title: name };
  const fraction =
    run.status === "running" || run.status === "waiting" ? (run.progress?.fraction ?? null) : null;
  const elapsed = run.started_at
    ? secondsBetween(run.started_at, run.finished_at ?? new Date(now).toISOString())
    : null;
  const ResultView = resultViewFor(run.agent_id);

  const cancel = async () => {
    setCancelling(true);
    setCancelError(undefined);
    try {
      await call(api.DELETE("/runs/{run_id}", { params: { path: { run_id: run.run_id } } }));
    } catch (err) {
      setCancelError((err as Error).message);
      setCancelling(false);
    }
  };

  return (
    <>
      <header className={`m-grid ${styles.runHead}`} data-live={live}>
        <div className={`m-note ${styles.runNote}`}>
          <StatusChip run={run} />
          {elapsed !== null && (
            <span className={styles.runClock}>{live ? clock(elapsed) : duration(elapsed)}</span>
          )}
          {run.llm && (
            <span title="The model this run uses">
              {PROVIDER_NAME[run.llm.provider as ProviderId] ?? run.llm.provider}
              {run.llm.model && (
                <>
                  {" "}
                  <code>{run.llm.model}</code>
                </>
              )}
            </span>
          )}
          <span className={styles.runId}>
            <span className="mono">{shortId(run.run_id)}</span>
            <CopyButton text={run.run_id} label="Copy run id" />
          </span>
        </div>

        <div className={styles.runMain}>
          <p className={styles.crumb}>
            <Link to="/runs" className="link" viewTransition>
              Runs
            </Link>
            <span aria-hidden="true">/</span>
            {live && (
              <>
                <Link to={`/agents/${run.agent_id}`} className="link" viewTransition>
                  {name}
                </Link>
                <span aria-hidden="true">/</span>
              </>
            )}
          </p>

          <div className={styles.runMessage} aria-live="polite">
            <h1 key={title} data-said={said || undefined}>
              {title}
            </h1>
            {detail && <p>{detail}</p>}
          </div>

          {(live || run.status === "cancelled") && (
            <div className={styles.progressRow}>
              <Progress
                value={run.status === "cancelled" ? (run.progress?.fraction ?? 0) : fraction}
                active={working}
                label={`${name} progress`}
              />
              <span className={styles.pct}>
                {run.status === "cancelled"
                  ? `stopped at ${Math.round((run.progress?.fraction ?? 0) * 100)}%`
                  : fraction !== null
                    ? `${Math.round(fraction * 100)}%`
                    : ""}
              </span>
            </div>
          )}

          <div className={styles.runActions}>
            {live ? (
              <Button variant="outlined" icon="close" onClick={cancel} disabled={cancelling}>
                {cancelling ? "Cancelling" : "Cancel"}
              </Button>
            ) : (
              <LinkButton
                variant="outlined"
                to={`/agents/${run.agent_id}`}
                state={again}
                icon="replay"
                title={
                  again ? "Opens the form with this run's input, to run again or change first" : undefined
                }
                viewTransition
              >
                {again ? "Run again" : "New run"}
              </LinkButton>
            )}
            {cancelError && <span className={styles.runError}>{cancelError}</span>}
          </div>
        </div>
      </header>

      {run.status === "waiting" && run.question ? (
        <QuestionForm key={run.question.id} runId={run.run_id} batch={run.question} />
      ) : null}

      <RunLog run={run} timeline={timeline} working={working} />

      {run.result && (run.status === "done" || run.result.status !== "error") ? (
        <Suspense fallback={<PageLoading label="Loading the result" />}>
          <ResultView run={run} result={run.result} />
        </Suspense>
      ) : run.status === "cancelled" ? (
        <EmptyState label="No result" title="Cancelled before it finished">
          <p>The run was cancelled before the agent finished, so there is nothing to show.</p>
        </EmptyState>
      ) : null}
    </>
  );
}
