/**
 * The loading indicator: a short stroke drawn again and again along a hairline, like a
 * pencil running under a line while reading it.
 */
import { Block } from "./Block";
import styles from "./Loading.module.css";

export function LoadingIndicator({ width = 120, label = "Loading" }: { width?: number; label?: string }) {
  return <span className={styles.line} role="progressbar" aria-label={label} style={{ width }} />;
}

/** A whole-page loading state: the label where the page's first line will be. */
export function PageLoading({ label = "Loading" }: { label?: string }) {
  return (
    <Block rule={false}>
      <p className={styles.page}>
        {label}
        <LoadingIndicator label={label} />
      </p>
    </Block>
  );
}
