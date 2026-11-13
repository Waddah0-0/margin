import { useAgents, useRuns } from "../api/hooks";
import { ListHead } from "../components/Block";
import { LinkButton } from "../components/Button";
import { PageLoading } from "../components/Loading";
import { PageHead } from "../components/PageHead";
import { RunList } from "../components/RunList";
import { EmptyState, ErrorState } from "../components/States";
import { usePageTitle } from "../lib/title";
import styles from "./pages.module.css";

export function RunsPage() {
  usePageTitle("Runs");
  const runs = useRuns(100);
  const agents = useAgents();

  return (
    <>
      <PageHead
        title="Runs"
        lede="Runs live in the API's memory: they are kept for an hour and forgotten when it restarts. Export a result to keep it."
      />

      {runs.loading && !runs.data && <PageLoading label="Loading runs" />}
      {runs.error && <ErrorState error={runs.error} onRetry={runs.reload} />}

      {runs.data && runs.data.length === 0 && (
        <EmptyState
          title="No runs yet"
          action={
            <LinkButton variant="filled" to="/agents" icon="play" viewTransition>
              Run an agent
            </LinkButton>
          }
        >
          <p>Start one from an agent's page and it will show up here.</p>
        </EmptyState>
      )}

      {runs.data && runs.data.length > 0 && (
        <section className={styles.section}>
          <ListHead label="Log" count={runs.data.length} />
          <RunList runs={runs.data} agents={agents.data?.agents ?? []} />
        </section>
      )}
    </>
  );
}
