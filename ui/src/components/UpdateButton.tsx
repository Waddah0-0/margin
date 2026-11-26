/**
 * Quiet top-bar update button: hidden when up to date. When a newer GitHub release exists,
 * hovering (or focusing) opens a popover showing what the update contains; clicking downloads
 * and launches the installer in the desktop app, or opens the release page in a browser.
 */
import { useEffect, useId, useRef, useState } from "react";
import { api, call, type UpdateStatus } from "../api/client";
import { Icon } from "./Icon";
import styles from "./UpdateButton.module.css";

interface NotesItem {
  id: string;
  text: string;
}

interface NotesBlock {
  id: string;
  kind: "heading" | "list" | "paragraph";
  text?: string;
  items?: NotesItem[];
}

function stripInlineMarkdown(line: string): string {
  return line
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .trim();
}

function parseReleaseNotes(raw: string): NotesBlock[] {
  const blocks: NotesBlock[] = [];
  let bullets: NotesItem[] = [];
  let seq = 0;

  const flushBullets = () => {
    if (bullets.length > 0) {
      blocks.push({ id: `list-${++seq}`, kind: "list", items: bullets });
      bullets = [];
    }
  };

  for (const rawLine of raw.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) {
      flushBullets();
      continue;
    }
    const heading = line.match(/^#{1,6}\s+(.+)$/);
    if (heading) {
      flushBullets();
      blocks.push({
        id: `heading-${++seq}`,
        kind: "heading",
        text: stripInlineMarkdown(heading[1] ?? ""),
      });
      continue;
    }
    const bullet = line.match(/^[-*+]\s+(.+)$/);
    if (bullet) {
      bullets.push({ id: `item-${++seq}`, text: stripInlineMarkdown(bullet[1] ?? "") });
      continue;
    }
    flushBullets();
    blocks.push({ id: `p-${++seq}`, kind: "paragraph", text: stripInlineMarkdown(line) });
  }
  flushBullets();
  return blocks;
}

function formatDate(iso?: string | null): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

export function UpdateButton() {
  const [status, setStatus] = useState<UpdateStatus>();
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<"idle" | "downloading" | "started">("idle");
  const [error, setError] = useState<string>();
  const closeTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const popoverId = useId();

  useEffect(() => {
    let live = true;
    call(api.GET("/updates")).then(
      (data) => {
        if (live) setStatus(data);
      },
      () => {
        // Offline or unreachable: stay hidden without disturbing the user.
      },
    );
    return () => {
      live = false;
      if (closeTimer.current) clearTimeout(closeTimer.current);
    };
  }, []);

  if (!status?.update_available || !status.latest_version) return null;

  const show = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    setOpen(true);
  };

  const scheduleHide = () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setOpen(false), 140);
  };

  const handleClick = async () => {
    if (phase !== "idle") return;
    if (!status.can_install) {
      if (status.release_url) {
        window.open(status.release_url, "_blank", "noopener,noreferrer");
      }
      return;
    }
    setPhase("downloading");
    setError(undefined);
    try {
      await call(api.POST("/updates/install"));
      setPhase("started");
    } catch (err) {
      setError((err as Error).message || "Could not install update");
      setPhase("idle");
      setOpen(true);
    }
  };

  const blocks = status.release_notes ? parseReleaseNotes(status.release_notes) : [];
  const published = formatDate(status.published_at);
  const label =
    phase === "downloading"
      ? "Downloading…"
      : phase === "started"
        ? "Installing…"
        : `Update v${status.latest_version}`;

  return (
    <div className={styles.wrap}>
      <button
        type="button"
        className={styles.trigger}
        onClick={() => void handleClick()}
        onMouseEnter={show}
        onMouseLeave={scheduleHide}
        onFocus={show}
        onBlur={scheduleHide}
        disabled={phase !== "idle"}
        aria-describedby={open ? popoverId : undefined}
      >
        <Icon name={phase === "idle" ? "download" : "spinner"} size={14} />
        <span>{label}</span>
      </button>

      {open && (
        <div
          id={popoverId}
          role="tooltip"
          className={styles.popover}
          onMouseEnter={show}
          onMouseLeave={scheduleHide}
        >
          <div className={styles.head}>
            <div>
              <p className={styles.title}>margin v{status.latest_version}</p>
              <p className={`mono ${styles.versions}`}>
                v{status.current_version} → v{status.latest_version}
              </p>
            </div>
            {published && <span className={styles.date}>{published}</span>}
          </div>

          <div className={styles.body}>
            {blocks.length > 0 ? (
              blocks.map((block) => {
                if (block.kind === "heading") {
                  return (
                    <h4 key={block.id} className={styles.heading}>
                      {block.text}
                    </h4>
                  );
                }
                if (block.kind === "list" && block.items) {
                  return (
                    <ul key={block.id} className={styles.list}>
                      {block.items.map((item) => (
                        <li key={item.id}>{item.text}</li>
                      ))}
                    </ul>
                  );
                }
                return (
                  <p key={block.id} className={styles.paragraph}>
                    {block.text}
                  </p>
                );
              })
            ) : (
              <p className={styles.paragraph}>
                A newer release of margin is available with fixes and improvements.
              </p>
            )}
          </div>

          {error && (
            <p className={styles.error} role="alert">
              {error}
            </p>
          )}

          <div className={styles.foot}>
            <span>
              {phase === "started"
                ? "Installer launched — margin will restart shortly."
                : status.can_install
                  ? "Click Update to download and install."
                  : "Click Update to open the GitHub release."}
            </span>
            {status.release_url && (
              <a
                href={status.release_url}
                target="_blank"
                rel="noreferrer"
                onFocus={show}
                onBlur={scheduleHide}
                className={`link ${styles.link}`}
              >
                Release notes
                <Icon name="open" size={11} />
              </a>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
