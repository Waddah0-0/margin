/**
 * The home page's launcher, written as a sentence: "Run <agent> on <its main input>".
 * Pick the agent, fill the blank, press Enter. When the main input is a file, choose (or
 * drop) one instead: it is uploaded, then the run starts. Agents without a main input, and
 * anyone wanting more options, continue on the agent's page.
 */
import { type DragEvent, type FormEvent, useEffect, useId, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import { type AgentInfo, uploadFile } from "../api/client";
import { startRun } from "../form/SchemaForm";
import { fieldsFromSchema } from "../form/schema";
import { Button } from "./Button";
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
  const [dragging, setDragging] = useState(false);
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
  const takesFile = primary?.kind === "file";

  // The menu is a popover: it lives in the top layer and the browser closes it on Escape or
  // a click outside. It is placed under the picker when it opens.
  useEffect(() => {
    const menu = menuRef.current;
    if (!menu) return;
    const onToggle = (e: Event) => {
      const open = (e as ToggleEvent).newState === "open";
      setMenuOpen(open);
      const rect = pickerRef.current?.getBoundingClientRect();
      if (open && rect) {
        menu.style.top = `${rect.bottom + 8}px`;
        menu.style.left = `${Math.max(8, Math.min(rect.left, window.innerWidth - 408))}px`;
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
    if (!takesFile) return;
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file && !busy) void sendFile(file);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (takesFile) {
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

  const carried = primary && !takesFile && text.trim() ? { [primary.name]: text.trim() } : undefined;

  return (
    <div className={styles.wrap}>
      <form
        className={styles.sentence}
        data-dragging={dragging || undefined}
        onSubmit={submit}
        onDragOver={(e) => {
          if (!takesFile) return;
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <span className={styles.word}>Run</span>
        <span className={styles.picker}>
          <button
            ref={pickerRef}
            type="button"
            className={styles.pick}
            popoverTarget={menuId}
            aria-haspopup="listbox"
            aria-expanded={menuOpen}
            aria-label={`Agent: ${agent.name}`}
          >
            {agent.name}
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
                <span className={styles.optionText}>
                  <span className={styles.optionName}>{a.name}</span>
                  <span className={styles.optionAbout}>{a.description}</span>
                </span>
                <Icon name="check" size={16} className={styles.optionCheck} />
              </button>
            ))}
          </div>
        </span>
        {primary && <span className={styles.word}>on</span>}
        {takesFile ? (
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
              className={`${styles.blank} ${styles.file}`}
              onClick={() => fileRef.current?.click()}
              disabled={busy}
            >
              {uploading
                ? `${uploading.name} (${Math.round(uploading.fraction * 100)}%)`
                : dragging
                  ? "drop it here"
                  : "a file you choose or drop"}
            </button>
          </>
        ) : primary ? (
          <input
            ref={inputRef}
            className={styles.blank}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={primary.placeholder ?? primary.label.toLowerCase()}
            aria-label={primary.label}
            spellCheck={false}
            autoComplete="off"
          />
        ) : null}
        <Button
          type="submit"
          size="l"
          trailingIcon={busy ? "spinner" : primary ? "enter" : "forward"}
          disabled={busy}
          className={styles.go}
        >
          {takesFile ? "Choose a file" : primary ? "Run" : "Open"}
        </Button>
      </form>
      <p className={styles.below}>
        {error ? (
          <span className={styles.error} role="alert">
            <Icon name="error" size={14} /> {error}
          </span>
        ) : (
          <span>
            {primary?.description ?? "This agent has no single main input. Its form has every field."}
          </span>
        )}
        <Link to={`/agents/${agent.id}`} state={carried} className="link" viewTransition>
          More options
        </Link>
      </p>
    </div>
  );
}
