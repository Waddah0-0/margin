/**
 * A run's progress, drawn on a ruler: ticks every tenth, an ink bar for the part that is
 * done, and a blue needle where the work is now. `value` null means the agent has not
 * said how far along it is, so a short bar travels the ruler instead.
 */
import type { CSSProperties } from "react";
import styles from "./Progress.module.css";

export function Progress({
  value,
  active = true,
  label,
}: {
  value: number | null;
  active?: boolean;
  label: string;
}) {
  const indeterminate = value === null;
  const pct = indeterminate ? 0 : Math.max(0, Math.min(1, value)) * 100;
  return (
    <div
      className={styles.ruler}
      data-active={active}
      data-indeterminate={indeterminate}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={indeterminate ? undefined : Math.round(pct)}
      style={{ "--pct": `${pct}%` } as CSSProperties}
    >
      <span className={styles.ticks} />
      <span className={styles.fill} />
      <span className={styles.needle} />
    </div>
  );
}
