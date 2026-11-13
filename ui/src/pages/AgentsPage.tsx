import { useAgents } from "../api/hooks";
import { AgentIndex } from "../components/AgentIndex";
import { Block, ListHead } from "../components/Block";
import { PageLoading } from "../components/Loading";
import { PageHead } from "../components/PageHead";
import { EmptyState, ErrorState } from "../components/States";
import { usePageTitle } from "../lib/title";
import styles from "./pages.module.css";

export function AgentsPage() {
  usePageTitle("Agents");
  const agents = useAgents();
  const list = agents.data?.agents ?? [];
  const failed = Object.entries(agents.data?.load_errors ?? {});

  return (
    <>
      <PageHead
        title="Agents"
        lede="Every agent installed alongside the API. Each one takes typed input and returns a result with its evidence."
      />

      {agents.loading && !agents.data && <PageLoading label="Loading agents" />}
      {agents.error && <ErrorState error={agents.error} onRetry={agents.reload} />}

      {failed.length > 0 && (
        <Block label="Failed to load" count={failed.length} tone="red">
          <ul className={styles.loadErrors} role="alert">
            {failed.map(([id, reason]) => (
              <li key={id}>
                <code>{id}</code>
                <span>{reason}</span>
              </li>
            ))}
          </ul>
        </Block>
      )}

      {agents.data && list.length === 0 && (
        <EmptyState title="No agents installed">
          <p>
            Agents are Python packages registered under the <code>margin.agents</code> entry point.
          </p>
        </EmptyState>
      )}

      {list.length > 0 && (
        <section className={styles.section}>
          <ListHead label="Installed" count={list.length} />
          <AgentIndex agents={list} />
        </section>
      )}
    </>
  );
}
