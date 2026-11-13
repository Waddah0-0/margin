import { describe, expect, it } from "vitest";
import {
  buildPayload,
  cliCommand,
  fieldsFromSchema,
  humanize,
  initialValues,
  valuesFromInput,
} from "./schema";

// The AI Code Detector's input schema, as the API returns it (trimmed).
const detector = {
  additionalProperties: false,
  properties: {
    paths: {
      anyOf: [{ items: { type: "string" }, type: "array" }, { type: "null" }],
      default: null,
      description: "Restrict the analysis to these files or folders.",
    },
    target: { description: "GitHub URL or local path.", type: "string" },
    use_llm_judge: { anyOf: [{ type: "boolean" }, { type: "null" }], default: null },
    max_files_for_judge: { default: 20, maximum: 200, minimum: 1, type: "integer" },
    max_judge_seconds: { default: 300.0, exclusiveMinimum: 0, type: "number" },
    include_tests: { default: false, type: "boolean" },
    mode: { $ref: "#/$defs/Mode", default: "fast" },
    extra: { type: "object" },
  },
  required: ["target"],
  $defs: { Mode: { enum: ["fast", "thorough"], type: "string" } },
};

describe("fieldsFromSchema", () => {
  const fields = fieldsFromSchema(detector, "target");
  const byName = Object.fromEntries(fields.map((f) => [f.name, f]));

  it("puts the primary input first", () => {
    expect(fields[0]?.name).toBe("target");
    expect(fields[0]?.primary).toBe(true);
    expect(fields[0]?.required).toBe(true);
  });

  it("maps types, nullables, enums and fallbacks", () => {
    expect(byName.paths?.kind).toBe("list");
    expect(byName.paths?.nullable).toBe(true);
    expect(byName.use_llm_judge?.kind).toBe("tristate");
    expect(byName.max_files_for_judge).toMatchObject({ kind: "integer", minimum: 1, maximum: 200 });
    expect(byName.include_tests?.kind).toBe("boolean");
    expect(byName.mode).toMatchObject({ kind: "choice", options: ["fast", "thorough"] });
    expect(byName.extra?.kind).toBe("json");
  });

  it("writes labels in sentence case", () => {
    expect(byName.max_files_for_judge?.label).toBe("Max files for judge");
    expect(humanize("use_llm_judge")).toBe("Use LLM judge");
    expect(humanize("max_cost_usd")).toBe("Max cost USD");
  });
});

describe("buildPayload", () => {
  const fields = fieldsFromSchema(detector, "target");

  it("sends only what differs from the defaults", () => {
    const values = { ...initialValues(fields), target: "  https://github.com/a/b " };
    expect(buildPayload(fields, values)).toEqual({
      payload: { target: "https://github.com/a/b" },
      errors: {},
    });
  });

  it("types changed values", () => {
    const values = {
      ...initialValues(fields),
      target: ".",
      paths: ["src", "lib"],
      use_llm_judge: false,
      max_files_for_judge: "5",
      include_tests: true,
      extra: '{"a": 1}',
    };
    expect(buildPayload(fields, values).payload).toEqual({
      target: ".",
      paths: ["src", "lib"],
      use_llm_judge: false,
      max_files_for_judge: 5,
      include_tests: true,
      extra: { a: 1 },
    });
  });

  it("reports missing and out-of-range values", () => {
    const values = {
      ...initialValues(fields),
      max_files_for_judge: "500",
      max_judge_seconds: "0",
      extra: "{",
    };
    expect(buildPayload(fields, values).errors).toEqual({
      target: "Required",
      max_files_for_judge: "At most 200",
      max_judge_seconds: "More than 0",
      extra: "Not valid JSON",
    });
  });
});

describe("valuesFromInput", () => {
  it("fills the form with a run's input, which builds the same body again", () => {
    const fields = fieldsFromSchema(detector, "target");
    const input = {
      target: "https://github.com/a/b",
      paths: ["src"],
      use_llm_judge: false,
      max_files_for_judge: 5,
    };
    const values = { ...initialValues(fields), ...valuesFromInput(fields, input) };
    expect(values.max_files_for_judge).toBe("5");
    expect(buildPayload(fields, values)).toEqual({ payload: input, errors: {} });
  });
});

describe("cliCommand with a model for the run", () => {
  it("adds the CLI's --provider and --model flags", () => {
    const fields = fieldsFromSchema({ properties: { message: { type: "string" } } }, "message");
    expect(cliCommand("echo", fields, { message: "hi" }, { provider: "anthropic", model: "claude-x" })).toBe(
      "margin run echo hi --provider anthropic --model claude-x",
    );
  });
});

describe("cliCommand", () => {
  it("matches the CLI's positional and --set syntax", () => {
    const fields = fieldsFromSchema(detector, "target");
    const payload = { target: "https://github.com/a/b", paths: ["src"], max_files_for_judge: 5 };
    expect(cliCommand("ai-code-detector", fields, payload)).toBe(
      `margin run ai-code-detector https://github.com/a/b -s 'paths=["src"]' -s max_files_for_judge=5`,
    );
    expect(
      cliCommand("echo", fieldsFromSchema({ properties: { message: { type: "string" } } }, "message"), {
        message: "it's me",
      }),
    ).toBe(`margin run echo 'it'\\''s me'`);
  });
});
