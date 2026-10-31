/**
 * Turn an agent's input JSON schema (as Pydantic writes it) into form fields, and form
 * values back into a request body. Anything the form cannot represent falls back to a
 * raw JSON field, so every agent can be run from the UI.
 */
import type { JsonSchema } from "../api/client";

export type FieldKind =
  | "text" // string
  | "integer"
  | "number"
  | "boolean" // true / false
  | "tristate" // true / false / null ("auto")
  | "choice" // enum of strings
  | "list" // array of strings
  | "file" // a path the user can also fill by uploading a file ("format": "file-path")
  | "json"; // anything else, edited as JSON

export interface Field {
  name: string;
  label: string;
  description?: string;
  kind: FieldKind;
  required: boolean;
  /** Accepts null; an empty value is sent as nothing (the agent's default). */
  nullable: boolean;
  primary: boolean;
  default?: unknown;
  options?: string[];
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  minLength?: number;
  maxLength?: number;
  placeholder?: string;
  /** For a file: the extensions to offer in the picker ("x-accept"). */
  accept?: string[];
}

/** Form state: text-like fields hold strings while typing; the payload is typed. */
export type FormValue = string | boolean | null | string[];
export type FormValues = Record<string, FormValue>;

const ACRONYMS = new Set(["llm", "url", "usd", "id", "api", "json", "ai", "sha"]);

/** `max_files_for_judge` -> "Max files for judge" (sentence case, acronyms kept). */
export function humanize(name: string): string {
  const words = name.split(/[_\s]+/).filter(Boolean);
  return words
    .map((w, i) => {
      const lower = w.toLowerCase();
      if (ACRONYMS.has(lower)) return lower.toUpperCase();
      return i === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower;
    })
    .join(" ");
}

function resolve(node: JsonSchema, root: JsonSchema): JsonSchema {
  const ref = node.$ref;
  if (typeof ref !== "string" || !ref.startsWith("#/")) return node;
  let target: unknown = root;
  for (const part of ref.slice(2).split("/")) {
    target = target && typeof target === "object" ? (target as JsonSchema)[part] : undefined;
  }
  return target && typeof target === "object"
    ? { ...(target as JsonSchema), ...node, $ref: undefined }
    : node;
}

function num(value: unknown): number | undefined {
  return typeof value === "number" ? value : undefined;
}

function fieldFor(name: string, raw: JsonSchema, root: JsonSchema): Omit<Field, "required" | "primary"> {
  let node = resolve(raw, root);
  let nullable = false;
  const variants = node.anyOf ?? node.oneOf;
  if (Array.isArray(variants)) {
    const options = (variants as JsonSchema[]).map((v) => resolve(v, root));
    const nonNull = options.filter((v) => v.type !== "null");
    nullable = nonNull.length < options.length;
    if (nonNull.length === 1 && nonNull[0]) {
      // keep the outer description/default/title, take the type from the variant
      node = { ...nonNull[0], ...node, anyOf: undefined, oneOf: undefined };
    } else {
      node = { ...node, type: undefined };
    }
  }
  const type = Array.isArray(node.type) ? undefined : (node.type as string | undefined);

  let kind: FieldKind = "json";
  let options: string[] | undefined;
  if (Array.isArray(node.enum) && node.enum.every((v) => typeof v === "string")) {
    kind = "choice";
    options = node.enum as string[];
  } else if (type === "string") kind = node.format === "file-path" ? "file" : "text";
  else if (type === "integer") kind = "integer";
  else if (type === "number") kind = "number";
  else if (type === "boolean") kind = nullable ? "tristate" : "boolean";
  else if (type === "array") {
    const items = node.items && typeof node.items === "object" ? resolve(node.items as JsonSchema, root) : {};
    if (items.type === "string") kind = "list";
  }

  const examples = Array.isArray(node.examples) ? node.examples : undefined;
  return {
    name,
    label: humanize(name),
    description: typeof node.description === "string" ? node.description : undefined,
    kind,
    nullable,
    default: node.default,
    options,
    minimum: num(node.minimum),
    maximum: num(node.maximum),
    exclusiveMinimum: num(node.exclusiveMinimum),
    exclusiveMaximum: num(node.exclusiveMaximum),
    minLength: num(node.minLength),
    maxLength: num(node.maxLength),
    placeholder: examples?.length ? String(examples[0]) : undefined,
    accept: Array.isArray(node["x-accept"]) ? (node["x-accept"] as unknown[]).map(String) : undefined,
  };
}

/** Fields in display order: the primary input, then required fields, then the rest. */
export function fieldsFromSchema(schema: JsonSchema, primaryInput?: string | null): Field[] {
  const properties = (schema.properties ?? {}) as Record<string, JsonSchema>;
  const required = new Set(Array.isArray(schema.required) ? (schema.required as string[]) : []);
  // an output folder is the API's to fill (each run gets its own, with downloads)
  const shown = Object.entries(properties).filter(
    ([, prop]) => resolve(prop, schema).format !== "output-dir",
  );
  const fields = shown.map(([name, prop]) => ({
    ...fieldFor(name, prop, schema),
    required: required.has(name),
    primary: name === primaryInput,
  }));
  const rank = (f: Field) => (f.primary ? 0 : f.required ? 1 : 2);
  return fields
    .map((f, i) => ({ f, i }))
    .sort((a, b) => rank(a.f) - rank(b.f) || a.i - b.i)
    .map(({ f }) => f);
}

export function initialValue(field: Field): FormValue {
  const d = field.default;
  switch (field.kind) {
    case "boolean":
      return d === true;
    case "tristate":
      return typeof d === "boolean" ? d : null;
    case "list":
      return Array.isArray(d) ? d.map(String) : [];
    case "json":
      return d === undefined || d === null ? "" : JSON.stringify(d, null, 2);
    default:
      return d === undefined || d === null ? "" : String(d);
  }
}

export function initialValues(fields: Field[]): FormValues {
  return Object.fromEntries(fields.map((f) => [f.name, initialValue(f)]));
}

/** The typed value for one field, or undefined when it should be left out. */
function typed(field: Field, value: FormValue): { ok: true; value: unknown } | { ok: false; error: string } {
  switch (field.kind) {
    case "boolean":
    case "tristate":
      return { ok: true, value };
    case "list":
      return { ok: true, value: Array.isArray(value) && value.length ? value : undefined };
    case "integer":
    case "number": {
      const text = String(value ?? "").trim();
      if (!text) return { ok: true, value: undefined };
      const n = Number(text);
      if (!Number.isFinite(n)) return { ok: false, error: "Enter a number" };
      if (field.kind === "integer" && !Number.isInteger(n))
        return { ok: false, error: "Enter a whole number" };
      if (field.minimum !== undefined && n < field.minimum)
        return { ok: false, error: `At least ${field.minimum}` };
      if (field.maximum !== undefined && n > field.maximum)
        return { ok: false, error: `At most ${field.maximum}` };
      if (field.exclusiveMinimum !== undefined && n <= field.exclusiveMinimum)
        return { ok: false, error: `More than ${field.exclusiveMinimum}` };
      if (field.exclusiveMaximum !== undefined && n >= field.exclusiveMaximum)
        return { ok: false, error: `Less than ${field.exclusiveMaximum}` };
      return { ok: true, value: n };
    }
    case "json": {
      const text = String(value ?? "").trim();
      if (!text) return { ok: true, value: undefined };
      try {
        return { ok: true, value: JSON.parse(text) };
      } catch {
        return { ok: false, error: "Not valid JSON" };
      }
    }
    default: {
      const text = String(value ?? "");
      if (!text.trim()) return { ok: true, value: undefined };
      if (field.minLength !== undefined && text.length < field.minLength)
        return { ok: false, error: `At least ${field.minLength} characters` };
      if (field.maxLength !== undefined && text.length > field.maxLength)
        return { ok: false, error: `At most ${field.maxLength} characters` };
      return { ok: true, value: text.trim() };
    }
  }
}

function sameAsDefault(field: Field, value: unknown): boolean {
  if (field.default === undefined) return value === null && field.nullable;
  return JSON.stringify(value) === JSON.stringify(field.default);
}

export interface Built {
  payload: Record<string, unknown>;
  errors: Record<string, string>;
}

/**
 * Validate the form and build the request body. Values equal to the agent's default are
 * left out, so the body (and the matching CLI command) only says what the user changed.
 */
export function buildPayload(fields: Field[], values: FormValues): Built {
  const payload: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const field of fields) {
    const result = typed(field, values[field.name] ?? initialValue(field));
    if (!result.ok) {
      errors[field.name] = result.error;
      continue;
    }
    if (result.value === undefined) {
      if (field.required) errors[field.name] = "Required";
      continue;
    }
    if (!field.required && sameAsDefault(field, result.value)) continue;
    payload[field.name] = result.value;
  }
  return { payload, errors };
}

function shellQuote(text: string): string {
  return /^[\w@%+=:,./-]+$/.test(text) ? text : `'${text.replaceAll("'", `'\\''`)}'`;
}

/** The same run as an `margin run` command line. */
export function cliCommand(
  agentId: string,
  fields: Field[],
  payload: Record<string, unknown>,
  llm?: { provider: string; model: string } | null,
): string {
  const parts = ["margin", "run", agentId];
  const primary = fields.find((f) => f.primary);
  if (primary && typeof payload[primary.name] === "string") {
    parts.push(shellQuote(payload[primary.name] as string));
  }
  for (const field of fields) {
    if (field === primary && typeof payload[field.name] === "string") continue;
    if (!(field.name in payload)) continue;
    const value = payload[field.name];
    const text = typeof value === "string" && field.kind === "text" ? value : JSON.stringify(value);
    parts.push("-s", shellQuote(`${field.name}=${text}`));
  }
  if (llm) {
    parts.push("--provider", llm.provider);
    if (llm.model) parts.push("--model", shellQuote(llm.model));
  }
  return parts.join(" ");
}
