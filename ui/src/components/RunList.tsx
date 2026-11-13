/**
 * Runs as a logbook: when each one started stands in the margin, and the line beside it
 * says which agent ran, what it concluded so far, and where it stands.
 */
import { Link } from "react-router";
import type { AgentInfo, RunView } from "../api/client";
import { duration, secondsBetween, shortId, timeAgo } from "../lib/format";
import styles from "./RunList.module.css";
import { StatusChip } from "./StatusChip";

export function RunList({ runs, agents }: { runs: RunView[]; agents: AgentInfo[] }) {
  const names = new Map(agents.map((a) => [a.id, a.name]));
  return (
    <ul className={styles.list}>
      {runs.map((run) => {
        const name = names.get(run.agent_id) ?? run.agent_id;
        const took = secondsBetween(run.started_at, run.finished_at);
        return (
          <li key={run.run_id}>
            <Link to={`/runs/${run.run_id}`} className={`m-grid ${styles.row}`} viewTransition>
              <span className={`m-note ${styles.when}`}>{timeAgo(run.created_at)}</span>
              <span className={styles.body}>
                <span className={styles.main}>
                  <span className={styles.name}>{name}</span>
                  <span className={styles.summary}>
                    {run.result?.summary ?? run.progress?.message ?? "Waiting to start"}
                  </span>
                </span>
                <span className={styles.meta}>
                  <StatusChip run={run} />
                  <span className={styles.small}>
                    {took !== null && run.finished_at ? `${duration(took)} · ` : ""}
                    <span className="mono">{shortId(run.run_id)}</span>
                  </span>
                </span>
              </span>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
