import { Link } from "react-router";
import { useAgents, useRuns } from "../api/hooks";
import { AgentIndex } from "../components/AgentIndex";
import { Block, ListHead } from "../components/Block";
import { Launcher } from "../components/Launcher";
import { LoadingIndicator } from "../components/Loading";
import { RunList } from "../components/RunList";
import { EmptyState, ErrorState } from "../components/States";
import styles from "./pages.module.css";

export function HomePage() {
  const agents = useAgents();
  const runs = useRuns(6);
  const list = agents.data?.agents ?? [];
  const loading = agents.loading && !agents.data;

  return (
    <>
      {(loading || list.length > 0) && (
        <Block rule={false} level={1} label="New run" className={styles.launch}>
          <p className={styles.pitch}>
            Small agents that show their work. Every finding comes with the evidence behind it, so you can
            check it instead of taking its word.
          </p>
          {loading ? <LoadingIndicator label="Loading agents" /> : <Launcher agents={list} />}
        </Block>
      )}

      {agents.error && <ErrorState error={agents.error} onRetry={agents.reload} />}

      {agents.data && list.length === 0 && (
        <EmptyState title="No agents installed">
          <p>
            Agents are Python packages registered under the <code>margin.agents</code> entry point. Install
            one alongside the API and it shows up here.
          </p>
        </EmptyState>
      )}

      {list.length > 0 && (
        <section className={styles.section}>
          <ListHead label="Agents" count={list.length}>
            <Link to="/agents" className="link" viewTransition>
              All agents
            </Link>
          </ListHead>
          <AgentIndex agents={list} />
        </section>
      )}

      {runs.data && runs.data.length > 0 && (
        <section className={styles.section}>
          <ListHead label="Recent runs">
            <Link to="/runs" className="link" viewTransition>
              All runs
            </Link>
          </ListHead>
          <RunList runs={runs.data} agents={list} />
        </section>
      )}
    </>
  );
}
