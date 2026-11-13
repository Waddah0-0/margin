/**
 * The frame around every page: the name and the navigation at the top, and a line of small
 * print at the bottom that says which API this page is talking to.
 */
import { NavLink } from "react-router";
import { API_LABEL, API_URL, api, call } from "../api/client";
import { useLoad } from "../api/hooks";
import { useTheme } from "../lib/theme";
import { Icon } from "./Icon";
import styles from "./Shell.module.css";

const ITEMS = [
  { to: "/agents", label: "Agents" },
  { to: "/runs", label: "Runs" },
  { to: "/settings", label: "Settings" },
] as const;

const THEME_ICON = { system: "systemTheme", light: "lightMode", dark: "darkMode" } as const;
const THEME_LABEL = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" } as const;

export function TopBar() {
  const [theme, cycleTheme] = useTheme();
  return (
    <header className={`m-grid ${styles.top}`}>
      <div className={`m-note ${styles.brandCell}`}>
        <NavLink to="/" className={styles.brand} aria-label="margin, home" viewTransition>
          margin
        </NavLink>
      </div>
      <div className={styles.bar}>
        <nav className={styles.nav} aria-label="Main">
          {ITEMS.map((item) => (
            <NavLink key={item.to} to={item.to} className={styles.item} viewTransition>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className={styles.tools}>
          <a className={styles.docs} href={`${API_URL}/docs`} target="_blank" rel="noreferrer">
            API docs
            <Icon name="open" size={12} />
          </a>
          <button type="button" className={styles.theme} onClick={cycleTheme} title={THEME_LABEL[theme]}>
            <Icon name={THEME_ICON[theme]} size={16} />
            <span className="visually-hidden">{THEME_LABEL[theme]}</span>
          </button>
        </div>
      </div>
    </header>
  );
}

export function Footer() {
  const health = useLoad(() => call(api.GET("/health")));
  const version = (health.data as { version?: string } | undefined)?.version;
  return (
    <footer className={`m-grid ${styles.foot}`}>
      <div className="m-note" />
      <p className={styles.footLine}>
        <span className={styles.api}>
          <span className={styles.signal} data-state={health.error ? "down" : health.data ? "up" : "wait"} />
          {health.error ? "No answer from the API at " : `margin-api${version ? ` ${version}` : ""} at `}
          <code>{API_LABEL}</code>
        </span>
        <a className="link" href={`${API_URL}/docs`} target="_blank" rel="noreferrer">
          API docs
        </a>
        <a className="link" href="https://github.com/Waddah0-0/margin" target="_blank" rel="noreferrer">
          Source
        </a>
      </p>
    </footer>
  );
}
