/**
 * The agents as an index: a number in the margin, then what each agent is called, what it
 * does, and what it needs. Every installed agent gets a line the same way, so a new one
 * appears here without anyone touching the page.
 */
import { Link } from "react-router";
import type { AgentInfo } from "../api/client";
import { fieldsFromSchema, humanize } from "../form/schema";
import styles from "./AgentIndex.module.css";
import { Icon } from "./Icon";

/** What an agent takes and needs, read from its schema. */
export function agentSpec(agent: AgentInfo): { takes?: string; options: number } {
  const fields = fieldsFromSchema(agent.input_schema, agent.primary_input);
  const primary = fields.find((f) => f.primary);
  return {
    takes: primary ? (primary.kind === "file" ? "a file" : humanize(primary.name).toLowerCase()) : undefined,
    options: fields.length - (primary ? 1 : 0),
  };
}

export function AgentIndex({ agents, gitAvailable = true }: { agents: AgentInfo[]; gitAvailable?: boolean }) {
  return (
    <ol className={styles.list}>
      {agents.map((agent, i) => {
        const spec = agentSpec(agent);
        const needsGit = Boolean(agent.requires_git) && !gitAvailable;
        return (
          <li key={agent.id}>
            <Link
              to={`/agents/${agent.id}`}
              className={`m-grid ${styles.row}`}
              data-unavailable={needsGit || undefined}
              viewTransition
            >
              <span className={`m-note ${styles.no}`}>{String(i + 1).padStart(2, "0")}</span>
              <span className={styles.body}>
                <span className={styles.text}>
                  <span className={styles.nameRow}>
                    <span className={styles.name}>{agent.name}</span>
                    {needsGit && (
                      <span className="tag" data-tone="red">
                        Needs git
                      </span>
                    )}
                  </span>
                  <span className={styles.description}>{agent.description}</span>
                </span>
                <span className={styles.spec}>
                  <span>{spec.takes ? `Takes ${spec.takes}` : "No single input"}</span>
                  <span>
                    {spec.options} {spec.options === 1 ? "option" : "options"}
                    {agent.uses_llm ? " · uses a model" : " · no model"}
                  </span>
                  <span className="mono">v{agent.version}</span>
                </span>
                <Icon name="forward" size={18} className={styles.arrow} />
              </span>
            </Link>
          </li>
        );
      })}
    </ol>
  );
}
