import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UpdateButton } from "./UpdateButton";

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

describe("UpdateButton", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("stays hidden when no newer version is available", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      jsonResponse({
        current_version: "0.1.3",
        latest_version: "0.1.3",
        update_available: false,
        can_install: false,
      }),
    );

    const { container } = render(<UpdateButton />);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(1));
    expect(container.firstChild).toBeNull();
  });

  it("shows release notes on hover and installs on click in desktop mode", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        jsonResponse({
          current_version: "0.1.3",
          latest_version: "0.1.5",
          update_available: true,
          release_url: "https://github.com/Waddah0-0/margin/releases/tag/v0.1.5",
          download_url: "https://github.com/Waddah0-0/margin/releases/download/v0.1.5/margin-setup-0.1.5.exe",
          asset_name: "margin-setup-0.1.5.exe",
          release_notes: "## What's new\n- Deep black dark mode\n- Power BI export",
          published_at: "2026-11-27T00:00:00Z",
          can_install: true,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          {
            status: "started",
            version: "0.1.5",
            installer_path: "C:\\Users\\test\\AppData\\Local\\margin\\updates\\margin-setup-0.1.5.exe",
          },
          202,
        ),
      );

    render(<UpdateButton />);
    const btn = await screen.findByRole("button", { name: /Update v0\.1\.5/ });

    // Hover opens the tooltip with parsed release notes
    fireEvent.mouseEnter(btn);
    expect(await screen.findByText("What's new")).toBeTruthy();
    expect(screen.getByText("Deep black dark mode")).toBeTruthy();
    expect(screen.getByText("Power BI export")).toBeTruthy();

    // Clicking triggers POST /updates/install
    fireEvent.click(btn);
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("button", { name: /Installing/ })).toBeTruthy();
  });
});
