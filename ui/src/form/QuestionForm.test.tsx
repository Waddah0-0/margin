import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { QuestionBatch } from "../api/client";
import { runLook } from "../components/StatusChip";
import { QuestionForm } from "./QuestionForm";

const batch: QuestionBatch = {
  id: "b1",
  title: "Check the data",
  detail: "Two things are unclear.",
  questions: [
    {
      id: "format",
      prompt: "Which date format does order_date use?",
      kind: "choice",
      choices: [
        { value: "mdy", label: "MM/DD/YYYY" },
        { value: "dmy", label: "DD/MM/YYYY", detail: "Day first" },
      ],
      default: "mdy",
      evidence: [{ kind: "sample", location: "order_date", detail: "01/02/2024, 03/04/2024" }],
      allow_other: false,
      required: true,
    },
    {
      id: "columns",
      prompt: "Which columns matter?",
      kind: "multi_choice",
      section: "Columns",
      choices: [
        { value: "revenue", label: "Revenue" },
        { value: "cost", label: "Cost" },
      ],
      allow_other: false,
      required: true,
    },
    {
      id: "grain",
      prompt: "One row is one what?",
      kind: "choice",
      section: "Columns",
      allow_other: true,
      required: true,
      choices: [{ value: "order", label: "An order" }],
    },
    { id: "note", prompt: "Anything else?", kind: "text", required: false, allow_other: false },
  ],
};

afterEach(() => vi.restoreAllMocks());

function answered() {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify({ run_id: "r1", status: "queued" }), {
      status: 202,
      headers: { "content-type": "application/json" },
    }),
  );
}

describe("QuestionForm", () => {
  it("shows the questions with their evidence and suggestions", () => {
    render(<QuestionForm runId="r1" batch={batch} />);
    expect(screen.getByRole("heading", { name: "Check the data" })).toBeTruthy();
    expect(screen.getByText("01/02/2024, 03/04/2024")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Columns" })).toBeTruthy();
    expect((screen.getByRole("radio", { name: /MM\/DD\/YYYY/ }) as HTMLInputElement).checked).toBe(true);
    expect(screen.getByText("Suggested")).toBeTruthy();
  });

  it("asks for the required answers before sending anything", async () => {
    const fetchMock = answered();
    const user = userEvent.setup();
    render(<QuestionForm runId="r1" batch={batch} />);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByText("Pick at least one")).toBeTruthy();
    expect(screen.getByText("Choose one")).toBeTruthy();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("posts every answer for this batch", async () => {
    const fetchMock = answered();
    const user = userEvent.setup();
    render(<QuestionForm runId="r1" batch={batch} />);
    await user.click(screen.getByRole("radio", { name: /DD\/MM\/YYYY/ }));
    await user.click(screen.getByRole("checkbox", { name: "Cost" }));
    await user.type(screen.getByRole("textbox", { name: /your own answer/ }), "order line");
    await user.click(screen.getByRole("button", { name: "Continue" }));

    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.url).toMatch(/\/runs\/r1\/answers$/);
    expect(await request.json()).toEqual({
      batch: "b1",
      answers: { format: "dmy", columns: ["cost"], grain: "order line", note: null },
    });
    expect(screen.getByRole("button", { name: "Sending" })).toBeTruthy();
  });

  it("shows why the API refused the answers", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "These questions have already been answered" }), {
        status: 409,
        headers: { "content-type": "application/json" },
      }),
    );
    const user = userEvent.setup();
    render(<QuestionForm runId="r1" batch={{ ...batch, questions: batch.questions.slice(0, 1) }} />);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect((await screen.findByRole("alert")).textContent).toBe("These questions have already been answered");
    expect(screen.getByRole("button", { name: "Continue" })).toBeTruthy();
  });
});

describe("runLook", () => {
  it("says a waiting run needs an answer", () => {
    const look = runLook({ status: "waiting" } as Parameters<typeof runLook>[0]);
    expect(look.label).toBe("Needs your answer");
  });
});
