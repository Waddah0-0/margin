import {
  type DragEvent,
  type KeyboardEvent,
  type ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { uploadFile } from "../api/client";
import { Button } from "../components/Button";
import { Icon } from "../components/Icon";
import { fileSize } from "../lib/format";
import styles from "./Fields.module.css";
import type { Field, FormValue } from "./schema";

export interface FieldProps {
  field: Field;
  value: FormValue;
  error?: string;
  onChange: (value: FormValue) => void;
  autoFocus?: boolean;
}

function Support({ id, field, error }: { id: string; field: Field; error?: string }) {
  const text = error ?? field.description;
  if (!text) return null;
  return (
    <p id={id} className={styles.support} data-error={Boolean(error)}>
      {error && <Icon name="error" size={16} />}
      {text}
    </p>
  );
}

function rangeHint(field: Field): string | undefined {
  const lo = field.minimum ?? field.exclusiveMinimum;
  const hi = field.maximum ?? field.exclusiveMaximum;
  if (lo !== undefined && hi !== undefined) return `${lo}–${hi}`;
  if (field.default !== undefined && field.default !== null) return `Default ${String(field.default)}`;
  return undefined;
}

export function TextField({ field, value, error, onChange, autoFocus }: FieldProps) {
  const id = useId();
  const numeric = field.kind === "integer" || field.kind === "number";
  const hint = numeric ? rangeHint(field) : undefined;
  return (
    <div className={styles.group}>
      <label className={styles.outlined} data-error={Boolean(error)} data-size={field.primary ? "l" : "m"}>
        <input
          className={styles.input}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.placeholder ?? " "}
          inputMode={field.kind === "integer" ? "numeric" : field.kind === "number" ? "decimal" : undefined}
          aria-invalid={Boolean(error)}
          aria-describedby={`${id}-support`}
          autoFocus={autoFocus}
          spellCheck={false}
          autoComplete="off"
        />
        <span className={styles.floating}>
          {field.label}
          {field.required && <span aria-hidden="true"> *</span>}
        </span>
        {hint && <span className={styles.suffix}>{hint}</span>}
      </label>
      <Support id={`${id}-support`} field={field} error={error} />
    </div>
  );
}

export function JsonField({ field, value, error, onChange }: FieldProps) {
  const id = useId();
  return (
    <div className={styles.group}>
      <label className={styles.outlined} data-error={Boolean(error)} data-multiline="true">
        <textarea
          className={`${styles.input} ${styles.code}`}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          placeholder=" "
          rows={4}
          aria-invalid={Boolean(error)}
          aria-describedby={`${id}-support`}
          spellCheck={false}
        />
        <span className={styles.floating}>{field.label} (JSON)</span>
      </label>
      <Support id={`${id}-support`} field={field} error={error} />
    </div>
  );
}

export function SwitchField({ field, value, onChange }: FieldProps) {
  const id = useId();
  return (
    <div className={styles.switchRow}>
      <div className={styles.switchText}>
        <label htmlFor={id} className={styles.switchLabel}>
          {field.label}
        </label>
        {field.description && <p className={styles.support}>{field.description}</p>}
      </div>
      <input
        id={id}
        type="checkbox"
        role="switch"
        aria-checked={value === true}
        className={styles.switch}
        checked={value === true}
        onChange={(e) => onChange(e.target.checked)}
      />
    </div>
  );
}

/** Segmented buttons (native radios underneath): for nullable booleans and short enums. */
export function SegmentedField({ field, value, onChange }: FieldProps) {
  const name = useId();
  const options: { label: string; value: FormValue }[] =
    field.kind === "tristate"
      ? [
          { label: "Auto", value: null },
          { label: "On", value: true },
          { label: "Off", value: false },
        ]
      : (field.options ?? []).map((o) => ({ label: o, value: o }));
  const current = value ?? (field.kind === "choice" ? String(field.default ?? "") : null);
  return (
    <fieldset className={`${styles.switchRow} ${styles.fieldset}`}>
      <div className={styles.switchText}>
        <legend className={styles.switchLabel}>{field.label}</legend>
        {field.description && <p className={styles.support}>{field.description}</p>}
      </div>
      <div className={styles.segmented}>
        {options.map((option) => (
          <label key={option.label} className={styles.segment}>
            <input
              type="radio"
              name={name}
              className="visually-hidden"
              checked={option.value === current}
              onChange={() => onChange(option.value)}
            />
            <span className={styles.check}>
              <Icon name="check" size={18} />
            </span>
            {option.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function SelectField({ field, value, onChange }: FieldProps) {
  const id = useId();
  return (
    <div className={styles.group}>
      <label className={styles.outlined} data-filled="true">
        <select
          id={id}
          className={styles.input}
          value={String(value ?? field.default ?? "")}
          onChange={(e) => onChange(e.target.value)}
        >
          {field.nullable && <option value="">Default</option>}
          {(field.options ?? []).map((o) => (
            <option key={o} value={o}>
              {o}
            </option>
          ))}
        </select>
        <span className={styles.floating}>{field.label}</span>
        <Icon name="dropdown" className={styles.dropdown} />
      </label>
      <Support id={`${id}-support`} field={field} />
    </div>
  );
}

/** A list of strings, edited as input chips: Enter or comma adds, Backspace removes. */
export function ListField({ field, value, error, onChange }: FieldProps) {
  const id = useId();
  const items = Array.isArray(value) ? value : [];
  const [draft, setDraft] = useState("");

  const add = (text: string) => {
    const parts = text
      .split(",")
      .map((p) => p.trim())
      .filter((p) => p && !items.includes(p));
    if (parts.length) onChange([...items, ...parts]);
    setDraft("");
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" || e.key === ",") {
      e.preventDefault();
      add(draft);
    } else if (e.key === "Backspace" && !draft && items.length) {
      onChange(items.slice(0, -1));
    }
  };

  return (
    <div className={styles.group}>
      <label
        className={styles.outlined}
        data-error={Boolean(error)}
        data-filled={items.length > 0 || undefined}
      >
        <span className={styles.chips}>
          {items.map((item) => (
            <span key={item} className={styles.chip}>
              <span className={styles.chipText}>{item}</span>
              <button
                type="button"
                className={styles.chipRemove}
                aria-label={`Remove ${item}`}
                onClick={(e) => {
                  e.preventDefault();
                  onChange(items.filter((i) => i !== item));
                }}
              >
                <Icon name="close" size={16} />
              </button>
            </span>
          ))}
          <input
            className={styles.input}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            onBlur={() => draft && add(draft)}
            placeholder=" "
            aria-describedby={`${id}-support`}
            spellCheck={false}
          />
        </span>
        <span className={styles.floating}>{field.label}</span>
      </label>
      <Support
        id={`${id}-support`}
        field={{
          ...field,
          description: field.description ? `${field.description} Press Enter to add.` : "Press Enter to add.",
        }}
        error={error}
      />
    </div>
  );
}

function baseName(path: string): string {
  return path.split(/[\\/]/).pop() || path;
}

type Upload =
  | { state: "idle" }
  | { state: "sending"; name: string; fraction: number }
  | { state: "done"; name: string; size: number };

/**
 * A path the agent reads, filled by uploading a file (drop it, or choose it) to the API,
 * which saves it and gives back the path. Typing a path on the API's machine still works.
 */
export function FileField({ field, value, error, onChange }: FieldProps) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);
  const [upload, setUpload] = useState<Upload>({ state: "idle" });
  const [typing, setTyping] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [failed, setFailed] = useState<string>();
  const path = String(value ?? "");

  useEffect(() => () => abort.current?.abort(), []);

  const send = async (file: File) => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setFailed(undefined);
    setUpload({ state: "sending", name: file.name, fraction: 0 });
    onChange("");
    try {
      const saved = await uploadFile(
        file,
        (fraction) => setUpload({ state: "sending", name: file.name, fraction }),
        controller.signal,
      );
      setUpload({ state: "done", name: saved.name, size: saved.size });
      onChange(saved.path);
    } catch (e) {
      setUpload({ state: "idle" });
      if (!(e instanceof DOMException && e.name === "AbortError"))
        setFailed(e instanceof Error ? e.message : "The upload failed");
    }
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file) void send(file);
  };

  const clear = () => {
    abort.current?.abort();
    setUpload({ state: "idle" });
    setFailed(undefined);
    onChange("");
  };

  if (typing) {
    return (
      <div className={styles.group}>
        <TextField
          field={{ ...field, kind: "text", description: "A path on the machine running the API." }}
          value={value}
          error={error}
          onChange={onChange}
          autoFocus
        />
        <button type="button" className={styles.switchMode} onClick={() => setTyping(false)}>
          Upload a file instead
        </button>
      </div>
    );
  }

  const problem = error ?? failed;
  const shown =
    upload.state === "done" ? upload : path ? { name: baseName(path), size: undefined } : undefined;
  return (
    <div className={styles.group}>
      <span className={styles.fileLabel} id={`${id}-label`}>
        {field.label}
        {field.required && <span aria-hidden="true"> *</span>}
      </span>
      <section
        className={styles.drop}
        data-dragging={dragging || undefined}
        data-error={problem ? true : undefined}
        aria-labelledby={`${id}-label`}
        aria-describedby={`${id}-support`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <input
          ref={input}
          type="file"
          className="visually-hidden"
          accept={field.accept?.join(",")}
          tabIndex={-1}
          aria-hidden="true"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void send(file);
            e.target.value = "";
          }}
        />
        {upload.state === "sending" ? (
          <div className={styles.sending}>
            <span className={styles.fileName}>
              <Icon name="spinner" size={18} /> Uploading {upload.name}
            </span>
            <progress
              className={styles.progress}
              max={1}
              value={upload.fraction}
              aria-label={`Uploading ${upload.name}`}
            />
            <Button variant="text" size="s" onClick={clear}>
              Cancel
            </Button>
          </div>
        ) : shown ? (
          <div className={styles.chosen}>
            <Icon name="file" size={22} />
            <span className={styles.fileName}>{shown.name}</span>
            {shown.size !== undefined && <span className={styles.fileSize}>{fileSize(shown.size)}</span>}
            <span className={styles.fileActions}>
              <Button variant="text" size="s" onClick={() => input.current?.click()}>
                Replace
              </Button>
              <Button variant="text" size="s" onClick={clear}>
                Remove
              </Button>
            </span>
          </div>
        ) : (
          <div className={styles.empty}>
            <Icon name="upload" size={24} />
            <span>Drop a file here, or</span>
            <Button variant="tonal" size="s" onClick={() => input.current?.click()}>
              Choose a file
            </Button>
          </div>
        )}
      </section>
      <p id={`${id}-support`} className={styles.support} data-error={Boolean(problem)}>
        {problem && <Icon name="error" size={16} />}
        {problem ?? field.description}
      </p>
      <button type="button" className={styles.switchMode} onClick={() => setTyping(true)}>
        Type a path on the server instead
      </button>
    </div>
  );
}

export function FieldInput(props: FieldProps) {
  const { field } = props;
  switch (field.kind) {
    case "boolean":
      return <SwitchField {...props} />;
    case "tristate":
      return <SegmentedField {...props} />;
    case "choice":
      return (field.options?.length ?? 0) <= 4 ? <SegmentedField {...props} /> : <SelectField {...props} />;
    case "list":
      return <ListField {...props} />;
    case "json":
      return <JsonField {...props} />;
    case "file":
      return <FileField {...props} />;
    default:
      return <TextField {...props} />;
  }
}

/** A labelled text field for hand-built forms (settings), in the same style as the generated ones. */
export function PlainTextField({
  label,
  value,
  onChange,
  type = "text",
  placeholder,
  support,
  error,
  list,
  disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: "text" | "password" | "url" | "number";
  placeholder?: string;
  support?: ReactNode;
  error?: string;
  list?: string;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className={styles.group}>
      <label
        className={styles.outlined}
        data-error={Boolean(error)}
        data-filled={placeholder ? true : undefined}
      >
        <input
          className={styles.input}
          type={type}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder ?? " "}
          aria-invalid={Boolean(error)}
          aria-describedby={`${id}-support`}
          list={list}
          disabled={disabled}
          spellCheck={false}
          autoComplete="off"
        />
        <span className={styles.floating}>{label}</span>
      </label>
      {(error || support) && (
        <p id={`${id}-support`} className={styles.support} data-error={Boolean(error)}>
          {error && <Icon name="error" size={16} />}
          {error ?? support}
        </p>
      )}
    </div>
  );
}
