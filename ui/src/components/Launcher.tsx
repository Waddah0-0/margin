/**
 * The home page's pill-shaped launcher: pick an agent, type its main input, go. When the
 * main input is a file, choose (or drop) one instead: it is uploaded, then the run starts.
 * Agents without a main input (or anyone wanting more options) continue on the agent's page.
 */
import { type DragEvent, type FormEvent, useEffect, useId, useRef, useState } from "react";
import { useNavigate } from "react-router";
import { type AgentInfo, uploadFile } from "../api/client";
import { startRun } from "../form/SchemaForm";
import { fieldsFromSchema } from "../form/schema";
import { AgentAvatar } from "./AgentAvatar";
import { IconButton } from "./Button";
import { Icon } from "./Icon";
import styles from "./Launcher.module.css";

const LAST_AGENT_KEY = "margin:last-agent";

function readLastAgent(): string | null {
  try {
    return localStorage.getItem(LAST_AGENT_KEY);
  } catch {
    return null;
  }
}

function saveLastAgent(id: string) {
  try {
    localStorage.setItem(LAST_AGENT_KEY, id);
  } catch {
    // private mode: the launcher just starts on the first agent next time
  }
}

export function Launcher({ agents }: { agents: AgentInfo[] }) {
  const navigate = useNavigate();
  // start on the agent used last time, so the launcher doesn't favour any one agent
  const [agentId, setAgentId] = useState(() => {
    const last = readLastAgent();
    return (agents.find((a) => a.id === last) ?? agents[0])?.id;
  });
  const [text, setText] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState<{ name: string; fraction: number }>();
  const [error, setError] = useState<string>();
  const menuId = useId();
  const pickerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const agent = agents.find((a) => a.id === agentId);
  const primary = agent
    ? fieldsFromSchema(agent.input_schema, agent.primary_input).find((f) => f.primary)
    : undefined;

  // The menu is a popover: it lives in the top layer (no clipping by the hero) and the
  // browser closes it on Escape or a click outside. It is placed under the picker on open.
  useEffect(() => {
    const menu = menuRef.current;
    if (!menu) return;
    const onToggle = (e: Event) => {
      const open = (e as ToggleEvent).newState === "open";
      setMenuOpen(open);
      const rect = pickerRef.current?.getBoundingClientRect();
      if (open && rect) {
        menu.style.top = `${rect.bottom + 14}px`;
        menu.style.left = `${Math.max(8, rect.left - 8)}px`;
      }
    };
    menu.addEventListener("beforetoggle", onToggle);
    return () => menu.removeEventListener("beforetoggle", onToggle);
  });

  if (!agent) return null;

  const go = async (value: string) => {
    if (!primary) return;
    try {
      const runId = await startRun(agent.id, { [primary.name]: value });
      saveLastAgent(agent.id);
      navigate(`/runs/${runId}`, { viewTransition: true });
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };

  const sendFile = async (file: File) => {
    setBusy(true);
    setError(undefined);
    setUploading({ name: file.name, fraction: 0 });
    try {
      const saved = await uploadFile(file, (fraction) => setUploading({ name: file.name, fraction }));
      await go(saved.path);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    } finally {
      setUploading(undefined);
    }
  };

  const onDrop = (e: DragEvent) => {
    if (primary?.kind !== "file") return;
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (file && !busy) void sendFile(file);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (primary?.kind === "file") {
      fileRef.current?.click();
      return;
    }
    if (!primary) {
      navigate(`/agents/${agent.id}`, { viewTransition: true });
      return;
    }
    if (!text.trim()) {
      inputRef.current?.focus();
      return;
    }
    setBusy(true);
    setError(undefined);
    await go(text.trim());
  };

  return (
    <div className={styles.wrap}>
      <form
        className={styles.pill}
        onSubmit={submit}
        onDragOver={(e) => primary?.kind === "file" && e.preventDefault()}
        onDrop={onDrop}
      >
        <div className={styles.picker}>
          <button
            ref={pickerRef}
            type="button"
            className={styles.pickerButton}
            popoverTarget={menuId}
            aria-haspopup="listbox"
            aria-expanded={menuOpen}
          >
            <AgentAvatar id={agent.id} name={agent.name} size={32} />
            <span className={styles.pickerName}>{agent.name}</span>
            <Icon name="unfold" size={20} />
          </button>
          <div
            ref={menuRef}
            id={menuId}
            popover="auto"
            className={styles.menu}
            role="listbox"
            aria-label="Agent"
          >
            {agents.map((a) => (
              <button
                key={a.id}
                type="button"
                role="option"
                aria-selected={a.id === agent.id}
                className={styles.option}
                onClick={() => {
                  setAgentId(a.id);
                  saveLastAgent(a.id);
                  menuRef.current?.hidePopover();
                  setError(undefined);
                  inputRef.current?.focus();
                }}
              >
                <AgentAvatar id={a.id} name={a.name} size={36} />
                <span className={styles.optionText}>
                  <span className="title-s">{a.name}</span>
                  <span className="body-s muted">{a.description}</span>
                </span>
                {a.id === agent.id && <Icon name="check" size={20} />}
              </button>
            ))}
          </div>
        </div>
        <span className={styles.divider} />
        {primary?.kind === "file" ? (
          <>
            <input
              ref={fileRef}
              type="file"
              className="visually-hidden"
              accept={primary.accept?.join(",")}
              tabIndex={-1}
              aria-hidden="true"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) void sendFile(file);
                e.target.value = "";
              }}
            />
            <button
              type="button"
              className={`${styles.input} ${styles.fileButton}`}
              onClick={() => fileRef.current?.click()}
              disabled={busy}
            >
              {uploading ? (
                <>
                  Uploading {uploading.name} ({Math.round(uploading.fraction * 100)}%)
                </>
              ) : (
                <>
                  <Icon name="upload" size={20} /> Choose or drop a file
                </>
              )}
            </button>
          </>
        ) : primary ? (
          <input
            ref={inputRef}
            className={styles.input}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={primary.placeholder ?? primary.description ?? primary.label}
            aria-label={primary.label}
            spellCheck={false}
            autoComplete="off"
          />
        ) : (
          <span className={`${styles.input} ${styles.placeholder}`}>This agent has no single main input</span>
        )}
        <IconButton
          type="submit"
          icon={busy ? "spinner" : "forward"}
          label={primary ? "Run" : "Open"}
          variant="filled"
          disabled={busy}
          className={styles.go}
        />
      </form>
      <div className={styles.below}>
        <button
          type="button"
          className={styles.more}
          onClick={() =>
            navigate(`/agents/${agent.id}`, {
              viewTransition: true,
              state:
                primary && primary.kind !== "file" && text.trim()
                  ? { [primary.name]: text.trim() }
                  : undefined,
            })
          }
        >
          <Icon name="options" size={16} />
          More options
        </button>
        {error && (
          <p className={styles.error} role="alert">
            <Icon name="error" size={16} /> {error}
          </p>
        )}
      </div>
    </div>
  );
}
