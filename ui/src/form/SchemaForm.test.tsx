import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentInfo } from "../api/client";
import { SchemaForm } from "./SchemaForm";

const agent: AgentInfo = {
  id: "echo",
  name: "Echo Agent",
  description: "Echoes its input back.",
  version: "0.1.0",
  primary_input: "message",
  uses_llm: false,
  requires_git: false,
  input_schema: {
    properties: {
      repeat: { default: 1, maximum: 10, minimum: 1, type: "integer", description: "How many times." },
      message: { minLength: 1, type: "string", description: "Text to echo back." },
      use_llm: { default: false, type: "boolean", description: "Also send it to the LLM." },
    },
    required: ["message"],
  },
  output_schema: {},
};

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

afterEach(() => vi.restoreAllMocks());

describe("SchemaForm", () => {
  it("puts the primary input first and optional fields under More options", () => {
    renderForm();
    const inputs = screen.getAllByRole("textbox");
    expect(inputs[0]?.closest("label")?.textContent).toContain("Message");
    expect(screen.getByText("More options").closest("details")).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Use LLM" })).toBeTruthy();
  });

  it("validates, then posts only changed values and opens the run", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ run_id: "abc", status: "queued", queue_position: 1, links: {} }), {
        status: 202,
        headers: { "content-type": "application/json" },
      }),
    );
    const user = userEvent.setup();
    renderForm();

    await user.click(screen.getByRole("button", { name: "Run" }));
    expect(screen.getByText("Required")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();

    await user.type(screen.getAllByRole("textbox")[0] as HTMLElement, "hello");
    expect(screen.getByText("margin run echo hello")).toBeTruthy(); // the live CLI preview
    await user.click(screen.getByRole("button", { name: "Run" }));

    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.url).toMatch(/\/agents\/echo\/runs$/);
    expect(await request.json()).toEqual({ message: "hello" });
    expect(await screen.findByText("run page")).toBeTruthy();
  });
});
