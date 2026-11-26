import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";
import type { AgentInfo } from "../api/client";
import { AgentIndex, agentSpec } from "./AgentIndex";

const agent = (id: string, extra: Partial<AgentInfo> = {}): AgentInfo => ({
  id,
  name: `Agent ${id.toUpperCase()}`,
  description: `Agent ${id} does one job.`,
  version: "0.1.0",
  primary_input: "target",
  uses_llm: false,
  requires_git: false,
  input_schema: {
    properties: { target: { type: "string" }, depth: { type: "integer", default: 1 } },
    required: ["target"],
  },
  output_schema: {},
  ...extra,
});

function renderIndex(agents: AgentInfo[], gitAvailable = true) {
  const router = createMemoryRouter([
    { path: "/", element: <AgentIndex agents={agents} gitAvailable={gitAvailable} /> },
  ]);
  return render(<RouterProvider router={router} />);
}

describe("AgentIndex", () => {
  it("lists every installed agent, numbered, each linking to its page", () => {
    renderIndex([agent("a"), agent("b", { uses_llm: true })]);
    const links = screen.getAllByRole("link");
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/agents/a", "/agents/b"]);
    expect(screen.getByText("01")).toBeTruthy();
    expect(screen.getByText("02")).toBeTruthy();
    expect(screen.getByText(/1 option · uses a model/)).toBeTruthy();
  });

  it("marks only git-dependent agents as needing git when git is unavailable", () => {
    renderIndex([agent("repo", { requires_git: true }), agent("file", { requires_git: false })], false);
    expect(screen.getAllByText("Needs git")).toHaveLength(1);
    const links = screen.getAllByRole("link");
    expect(links[0]?.getAttribute("data-unavailable")).toBe("true");
    expect(links[1]?.getAttribute("data-unavailable")).toBeNull();
  });

  it("reads what an agent takes from its schema", () => {
    expect(agentSpec(agent("a"))).toEqual({ takes: "target", options: 1 });
    const file = agent("f", {
      primary_input: "dataset",
      input_schema: { properties: { dataset: { type: "string", format: "file-path" } } },
    });
    expect(agentSpec(file)).toEqual({ takes: "a file", options: 0 });
    expect(agentSpec(agent("n", { primary_input: null }))).toEqual({ takes: undefined, options: 2 });
  });
});
