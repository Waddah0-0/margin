import type { RunView } from "../api/client";
import { ordinal } from "../lib/format";
import { Icon } from "./Icon";
import type { IconName } from "./icons";
import styles from "./StatusChip.module.css";

type Look = { tone: string; icon: IconName; label: string };

/** One label for where a run stands, combining the run status and the result status. */
export function runLook(run: RunView): Look {
  switch (run.status) {
    case "queued":
      return {
        tone: "neutral",
        icon: "queued",
        label: run.queue_position ? `Queued, ${ordinal(run.queue_position)} in line` : "Queued",
      };
    case "running":
      return { tone: "active", icon: "spinner", label: "Running" };
    case "waiting":
      return { tone: "warn", icon: "question", label: "Needs your answer" };
    case "cancelled":
      return { tone: "neutral", icon: "block", label: "Cancelled" };
    default:
      if (run.result?.status === "error") return { tone: "error", icon: "error", label: "Failed" };
      if (run.result?.status === "partial") return { tone: "warn", icon: "warning", label: "Partial" };
      return { tone: "ok", icon: "checkCircle", label: "Done" };
  }
}

export function StatusChip({ run }: { run: RunView }) {
  const look = runLook(run);
  return (
    <span className={styles.chip} data-tone={look.tone}>
      <Icon name={look.icon} size={16} fill={look.tone === "ok"} />
      {look.label}
    </span>
  );
}
