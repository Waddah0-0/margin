import type { ReactNode } from "react";
import { API_LABEL, ApiUnreachable } from "../api/client";
import { Block } from "./Block";
import { Button } from "./Button";
import { CopyButton } from "./CopyButton";
import styles from "./States.module.css";

/**
 * What a page says when it has nothing to show: a plain statement where the content would
 * be, what to do about it, and a word in the margin for the kind of nothing it is.
 */
export function EmptyState({
  title,
  children,
  action,
  tone = "neutral",
  label,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  tone?: "neutral" | "error";
  /** The word in the margin. Defaults to "Empty", or "Error" for the error tone. */
  label?: string;
}) {
  const error = tone === "error";
  return (
    <Block label={label ?? (error ? "Error" : "Empty")} tone={error ? "red" : undefined} rule={false}>
      <div className={styles.empty}>
        <h2 className={styles.title}>{title}</h2>
        {children && <div className={styles.body}>{children}</div>}
        {action && <div className={styles.action}>{action}</div>}
      </div>
    </Block>
  );
}

/** What to show when a request failed: how to start the API, or the error itself. */
export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  const retry = onRetry && (
    <Button variant="outlined" icon="refresh" onClick={onRetry}>
      Try again
    </Button>
  );
  if (error instanceof ApiUnreachable) {
    return (
      <EmptyState title="Can't reach the API" label="Offline" tone="error" action={retry}>
        <p>
          The UI talks to the margin API at <code>{API_LABEL}</code>. Start it from the repository:
        </p>
        <div className={styles.command}>
          <code>uv run margin-api</code>
          <CopyButton text="uv run margin-api" label="Copy command" />
        </div>
      </EmptyState>
    );
  }
  return (
    <EmptyState title="Something went wrong" tone="error" action={retry}>
      <p>{error.message}</p>
    </EmptyState>
  );
}
