/** The top of a page: its title, a sentence about it, and small print in the margin. */
import type { ReactNode } from "react";
import { Link } from "react-router";
import styles from "./PageHead.module.css";

export function PageHead({
  title,
  lede,
  note,
  crumb,
  children,
}: {
  title: ReactNode;
  lede?: ReactNode;
  /** Small print for the margin, one line per child. */
  note?: ReactNode;
  /** The page this one belongs under. */
  crumb?: { to: string; label: string };
  children?: ReactNode;
}) {
  return (
    <header className={`m-grid ${styles.head}`}>
      <div className={`m-note ${styles.note}`}>{note}</div>
      <div className={styles.content}>
        {crumb && (
          <p className={styles.crumb}>
            <Link to={crumb.to} className="link" viewTransition>
              {crumb.label}
            </Link>
            <span aria-hidden="true">/</span>
          </p>
        )}
        <h1 className={styles.title}>{title}</h1>
        {lede && <p className={styles.lede}>{lede}</p>}
        {children}
      </div>
    </header>
  );
}
