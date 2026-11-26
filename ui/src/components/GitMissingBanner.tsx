import { Block } from "./Block";
import styles from "./GitMissingBanner.module.css";

const GIT_DOWNLOAD_URL = "https://git-scm.com/downloads";

/**
 * Shown when ``git`` is not on PATH so people know why repository agents are disabled
 * while file-based agents (like Data Storyteller) continue to work normally.
 */
export function GitMissingBanner({ agentName }: { agentName?: string }) {
  return (
    <Block label="Git missing" tone="red" className={styles.banner}>
      <p className={styles.text} role="status">
        <strong>Git was not found on your PATH.</strong>{" "}
        {agentName
          ? `${agentName} reads git repositories and is disabled until Git is installed. `
          : "Agents that inspect repositories are disabled until Git is installed. File agents like Data Storyteller still work normally. "}
        <a href={GIT_DOWNLOAD_URL} target="_blank" rel="noreferrer" className="link">
          Install Git
        </a>{" "}
        and restart margin.
      </p>
    </Block>
  );
}
