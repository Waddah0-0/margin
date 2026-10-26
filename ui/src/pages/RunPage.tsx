import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { api, call, isFinished, type ProgressEvent, type RunView } from "../api/client";
import { useAgents, useLiveRun } from "../api/hooks";
import { PROVIDER_NAME, type ProviderId } from "../api/settings";
import { AgentAvatar } from "../components/AgentAvatar";
import { Button, LinkButton } from "../components/Button";
import { CopyButton } from "../components/CopyButton";
import { Icon } from "../components/Icon";
import { PageLoading } from "../components/Loading";
import { Minimap } from "../components/Minimap";
import { EmptyState, ErrorState } from "../components/States";
import { StatusChip } from "../components/StatusChip";
import { WavyProgress } from "../components/WavyProgress";
import { QuestionForm } from "../form/QuestionForm";
import { duration, ordinal, secondsBetween, shortId } from "../lib/format";
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

function headline(run: RunView, cancelling: boolean): { title: string; detail?: string } {
  const took = secondsBetween(run.started_at, run.finished_at);
  switch (run.status) {
    case "queued":
      return {
        title: "Waiting for its turn",
        detail: run.queue_position
          ? `${ordinal(run.queue_position)} in line. Agents that use a model run one at a time.`
          : undefined,
      };
    case "running":
      return {
        title: cancelling ? "Stopping…" : (run.progress?.message ?? "Starting"),
        detail: cancelling
          ? "The agent stops at its next checkpoint; a model call in progress finishes first."
          : undefined,
      };
    case "waiting":
      return {
        title: cancelling ? "Stopping…" : "Waiting for your answer",
        detail: "The agent paused to ask you something. It carries on once you answer.",
      };
    case "cancelled":
      return { title: "Cancelled", detail: took ? `After ${duration(took)}.` : undefined };
    default:
      if (run.result?.status === "error")
        return { title: "The run failed", detail: took ? `After ${duration(took)}.` : undefined };
      return { title: took !== null ? `Finished in ${duration(took)}` : "Finished" };
  }
}

/** Stages in the order they first appeared; the last one is current while running. */
function stagesOf(timeline: ProgressEvent[]): string[] {
  const seen: string[] = [];
  for (const event of timeline) if (!seen.includes(event.stage)) seen.push(event.stage);
  return seen.filter((s) => s !== "done");
}

const humanStage = (stage: string) => stage.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());

export function RunPage() {
  const { runId = "" } = useParams();
  const { run, timeline, error, missing } = useLiveRun(runId);
  const agents = useAgents();
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState<string>();
  const live = run ? !isFinished(run.status) : false;
  const working = live && run?.status !== "waiting";
  const now = useNow(live);

  if (missing) {
    return (
      <div className={styles.page}>
        <EmptyState
          icon="expired"
          title="This run is no longer here"
          action={
            <LinkButton variant="tonal" to="/runs" icon="history">
              Recent runs
            </LinkButton>
          }
        >
          <p>Runs are kept in memory for an hour, and are lost when the API restarts.</p>
        </EmptyState>
      </div>
    );
  }
  if (error && !run) {
    return (
      <div className={styles.page}>
        <ErrorState error={error} onRetry={() => window.location.reload()} />
      </div>
    );
  }
  if (!run) return <PageLoading label="Loading run" />;

  const agent = agents.data?.agents.find((a) => a.id === run.agent_id);
  const name = agent?.name ?? run.agent_id;
  const { title, detail } = headline(
    run,
    cancelling && (run.status === "running" || run.status === "waiting"),
  );
  const fraction =
    run.status === "done"
      ? 1
      : run.status === "running" || run.status === "waiting"
        ? (run.progress?.fraction ?? null)
        : null;
  const stages = stagesOf(timeline);
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
    <div className={styles.page}>
      <section className={styles.runHero} data-live={live}>
        <div className={styles.runMain}>
          <div className={styles.runTop}>
            <Link to={`/agents/${run.agent_id}`} className={styles.runAgent} viewTransition>
              <AgentAvatar id={run.agent_id} name={name} size={40} />
              <span>{name}</span>
            </Link>
            <StatusChip run={run} />
            {run.llm && (
              <span className={styles.modelChip} title="The model this run uses">
                <Icon name={run.llm.provider === "local" ? "device" : "cloud"} size={14} />
                {PROVIDER_NAME[run.llm.provider as ProviderId] ?? run.llm.provider}
                {run.llm.model && <code>{run.llm.model}</code>}
              </span>
            )}
            <span className={styles.runId}>
              <span className="mono">run {shortId(run.run_id)}</span>
              <CopyButton text={run.run_id} label="Copy run id" />
            </span>
          </div>

          <div className={styles.runMessage} aria-live="polite">
            <h1 key={title}>{title}</h1>
            {detail && <p className="body-l muted">{detail}</p>}
          </div>

          <div className={styles.progressRow}>
            <WavyProgress
              value={run.status === "cancelled" ? (run.progress?.fraction ?? 0) : fraction}
              active={working}
              label={`${name} progress`}
            />
            {fraction !== null && <span className={styles.pct}>{Math.round(fraction * 100)}%</span>}
          </div>

          {stages.length > 0 && (
            <ol className={styles.stages} aria-label="Stages">
              {stages.map((stage, i) => {
                const current = working && i === stages.length - 1;
                return (
                  <li key={stage} className={styles.stage} data-current={current}>
                    <Icon name={current ? "spinner" : "check"} size={16} />
                    {humanStage(stage)}
                  </li>
                );
              })}
            </ol>
          )}

          <div className={styles.runActions}>
            {live ? (
              <Button variant="outlined" icon="close" onClick={cancel} disabled={cancelling}>
                {cancelling ? "Cancelling" : "Cancel"}
              </Button>
            ) : (
              <LinkButton variant="tonal" to={`/agents/${run.agent_id}`} icon="replay" viewTransition>
                New run
              </LinkButton>
            )}
            {cancelError && (
              <span className="body-m" style={{ color: "var(--error)" }}>
                {cancelError}
              </span>
            )}
            {elapsed !== null && live && (
              <span className={`body-m ${styles.elapsed}`}>{clock(elapsed)} elapsed</span>
            )}
          </div>
        </div>
        <div className={styles.runArt}>
          <Minimap
            seed={run.run_id}
            rows={14}
            reading={working}
            highlights={run.status === "done" && run.result?.status !== "error" ? [2, 7, 11] : []}
          />
        </div>
      </section>

      {run.status === "waiting" && run.question ? (
        <QuestionForm key={run.question.id} runId={run.run_id} batch={run.question} />
      ) : null}

      {run.result && (run.status === "done" || run.result.status !== "error") ? (
        <ResultView run={run} result={run.result} />
      ) : run.status === "cancelled" ? (
        <EmptyState icon="block" title="No result">
          <p>The run was cancelled before the agent finished, so there is nothing to show.</p>
        </EmptyState>
      ) : null}
    </div>
  );
}
