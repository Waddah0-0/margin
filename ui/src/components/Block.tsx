/**
 * The unit every page is built from: a note in the margin (a label, a count, a line or two
 * of small print) and the content it belongs to, on the other side of the ruled line.
 */
import type { ReactNode } from "react";
import styles from "./Block.module.css";

export function Block({
  label,
  count,
  note,
  tone,
  rule = true,
  level = 2,
  className,
  children,
}: {
  /** The heading that hangs in the margin. */
  label?: ReactNode;
  count?: number;
  /** Small print under the label: what kind of thing this is, when, how many. */
  note?: ReactNode;
  tone?: "red" | "blue";
  /** A hairline above the content. The first block on a page goes without. */
  rule?: boolean;
  /** The label's heading level; 0 for a label that is not a heading. */
  level?: 0 | 1 | 2 | 3;
  className?: string;
  children?: ReactNode;
}) {
  const Heading = (level ? `h${level}` : "p") as "h1" | "h2" | "h3" | "p";
  return (
    <section className={["m-grid", styles.block, className].filter(Boolean).join(" ")} data-rule={rule}>
      <div className={`m-note ${styles.margin}`}>
        {label && (
          <Heading className={styles.label} data-tone={tone}>
            {label}
            {count !== undefined && <span className={styles.count}>{count}</span>}
          </Heading>
        )}
        {note && <div className={styles.note}>{note}</div>}
      </div>
      <div className={styles.content}>{children}</div>
    </section>
  );
}

/**
 * The head of a list whose rows carry their own margin notes (a log, an index): the label
 * in the margin, a firm rule, and room on the right for one link.
 */
export function ListHead({
  label,
  count,
  children,
}: {
  label: string;
  count?: number;
  children?: ReactNode;
}) {
  return (
    <div className={`m-grid ${styles.head}`}>
      <div className="m-note">
        <h2 className={styles.label}>
          {label}
          {count !== undefined && <span className={styles.count}>{count}</span>}
        </h2>
      </div>
      <div className={styles.headContent}>{children}</div>
    </div>
  );
}
