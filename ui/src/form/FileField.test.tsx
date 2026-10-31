import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentInfo, AgentResult, RunView } from "../api/client";
import { ExportButtons } from "../results/GenericResult";
import { SchemaForm } from "./SchemaForm";
import { buildPayload, fieldsFromSchema, initialValues } from "./schema";

// The Data Storyteller's file fields, as the API returns them (trimmed).
const agent: AgentInfo = {
  id: "data-storyteller",
  name: "Data Storyteller",
  description: "Cleans a table.",
  version: "0.1.0",
  primary_input: "dataset",
  uses_llm: false, // the model badge would fetch settings too
  input_schema: {
    properties: {
      dataset: {
        description: "Path to the data.",
        format: "file-path",
        "x-accept": [".csv", ".xlsx"],
        minLength: 1,
        type: "string",
      },
      output_dir: {
        anyOf: [{ type: "string" }, { type: "null" }],
        default: null,
        format: "output-dir",
        description: "Folder for the cleaned data.",
      },
    },
    required: ["dataset"],
  },
  output_schema: {},
};

/** Stands in for XMLHttpRequest: answers each upload with `FakeXHR.reply`. */
class FakeXHR {
  static reply: { status: number; body: unknown } = { status: 201, body: {} };
  static sent: { url: string; body: unknown }[] = [];
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } =
    {
      onprogress: null,
    };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  status = 0;
  responseText = "";
  private url = "";

  open(_method: string, url: string) {
    this.url = url;
  }
  setRequestHeader() {}
  abort() {
    this.onabort?.();
  }
  send(body: unknown) {
    FakeXHR.sent.push({ url: this.url, body });
    queueMicrotask(() => {
      this.upload.onprogress?.({ lengthComputable: true, loaded: 1, total: 2 });
      this.status = FakeXHR.reply.status;
      this.responseText = JSON.stringify(FakeXHR.reply.body);
      this.onload?.();
    });
  }
}

function renderForm() {
  const router = createMemoryRouter(
    [
      { path: "/", element: <SchemaForm agent={agent} /> },
      { path: "/runs/:id", element: <p>run page</p> },
    ],
    { initialEntries: ["/"] },
  );
  return render(<RouterProvider router={router} />);
}

const fileInput = (container: HTMLElement) =>
  container.querySelector('input[type="file"]') as HTMLInputElement;

beforeEach(() => {
  FakeXHR.sent = [];
  vi.stubGlobal("XMLHttpRequest", FakeXHR);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("file fields", () => {
  it("are files with the accepted types, and the output folder is left to the API", () => {
    const fields = fieldsFromSchema(agent.input_schema, agent.primary_input);
    expect(fields.map((f) => f.name)).toEqual(["dataset"]);
    expect(fields[0]).toMatchObject({ kind: "file", accept: [".csv", ".xlsx"] });
    const payload = buildPayload(fields, { ...initialValues(fields), dataset: "/tmp/a.csv" });
    expect(payload).toEqual({ payload: { dataset: "/tmp/a.csv" }, errors: {} });
  });

  it("uploads the chosen file and runs on the saved path", async () => {
    FakeXHR.reply = {
      status: 201,
      body: { path: "/srv/uploads/1/sales.csv", name: "sales.csv", size: 2400 },
    };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ run_id: "abc", status: "queued", queue_position: 1, links: {} }), {
        status: 202,
        headers: { "content-type": "application/json" },
      }),
    );
    const user = userEvent.setup();
    const { container } = renderForm();
    expect(fileInput(container).accept).toBe(".csv,.xlsx");

    await user.upload(fileInput(container), new File(["a,b\n1,2\n"], "sales.csv", { type: "text/csv" }));
    expect(await screen.findByText("sales.csv")).toBeTruthy();
    expect(screen.getByText("2.4 KB")).toBeTruthy();
    expect(FakeXHR.sent[0]?.url).toMatch(/\/uploads\?name=sales\.csv$/);

    await user.click(screen.getByRole("button", { name: "Run" }));
    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(await request.json()).toEqual({ dataset: "/srv/uploads/1/sales.csv" });
    expect(await screen.findByText("run page")).toBeTruthy();
  });

  it("says why an upload was refused", async () => {
    FakeXHR.reply = { status: 413, body: { detail: "The file is larger than the 200 MB limit" } };
    const user = userEvent.setup();
    const { container } = renderForm();
    await user.upload(fileInput(container), new File(["x"], "huge.csv"));
    expect(await screen.findByText("The file is larger than the 200 MB limit")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Choose a file" })).toBeTruthy();
  });

  it("can take a typed path instead", async () => {
    const user = userEvent.setup();
    renderForm();
    await user.click(screen.getByRole("button", { name: "Type a path on the server instead" }));
    expect(screen.getByRole("textbox")).toBeTruthy();
    expect(screen.getByText("A path on the machine running the API.")).toBeTruthy();
  });
});

describe("ExportButtons", () => {
  it("offers the files a run wrote for download", () => {
    const run = {
      run_id: "0123456789abcdef",
      files: [{ name: "sales.clean.csv", size: 2400 }],
    } as unknown as RunView;
    const result = { agent_id: "data-storyteller" } as AgentResult;
    render(<ExportButtons run={run} result={result} />);
    const link = screen.getByRole("link", { name: /sales\.clean\.csv/ });
    expect(link.getAttribute("href")).toMatch(/\/runs\/0123456789abcdef\/files\/sales\.clean\.csv$/);
    expect(link.getAttribute("download")).toBe("sales.clean.csv");
  });
});
