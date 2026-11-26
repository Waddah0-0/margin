import { Suspense } from "react";
import { useLocation, useParams } from "react-router";
import { useAgents } from "../api/hooks";
import { LinkButton } from "../components/Button";
import { GitMissingBanner } from "../components/GitMissingBanner";
import { PageLoading } from "../components/Loading";
import { PageHead } from "../components/PageHead";
import { EmptyState, ErrorState } from "../components/States";
import { SchemaForm } from "../form/SchemaForm";
import type { FormValues } from "../form/schema";
import { usePageTitle } from "../lib/title";
import { agentIntroFor } from "../results/registry";

export function AgentPage() {
  const { agentId = "" } = useParams();
  const location = useLocation();
  const agents = useAgents();
  const agent = agents.data?.agents.find((a) => a.id === agentId);
  const gitAvailable = agents.data?.git_available ?? true;
  const loadError = agents.data?.load_errors?.[agentId];
  const Intro = agentIntroFor(agentId);
  usePageTitle(agent?.name ?? agentId);

  if (agents.loading && !agents.data) return <PageLoading label="Loading agent" />;
  if (agents.error) return <ErrorState error={agents.error} onRetry={agents.reload} />;
  if (!agent) {
    return (
      <EmptyState
        tone={loadError ? "error" : "neutral"}
        label={loadError ? "Error" : "Not found"}
        title={loadError ? `${agentId} failed to load` : `No agent called “${agentId}”`}
        action={
          <LinkButton variant="outlined" to="/agents" icon="back">
            All agents
          </LinkButton>
        }
      >
        {loadError && <p>{loadError}</p>}
      </EmptyState>
    );
  }

  const needsGit = Boolean(agent.requires_git) && !gitAvailable;

  return (
    <>
      <PageHead
        crumb={{ to: "/agents", label: "Agents" }}
        title={agent.name}
        lede={agent.description}
        note={
          <>
            <code>{agent.id}</code>
            <span>version {agent.version}</span>
            {agent.uses_llm && (
              <span title="Runs one at a time, because a local model has one GPU">uses a model</span>
            )}
          </>
        }
      />
      {needsGit && <GitMissingBanner agentName={agent.name} />}
      <SchemaForm
        key={agent.id}
        agent={agent}
        initial={(location.state as FormValues | null) ?? undefined}
        disabledReason={needsGit ? "Install Git and restart margin to run this agent." : undefined}
      />
      {Intro && (
        <Suspense fallback={null}>
          <Intro agent={agent} />
        </Suspense>
      )}
    </>
  );
}
