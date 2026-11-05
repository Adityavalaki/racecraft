import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DataChooser } from "./DataChooser";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function serve(ok = true) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${url}`);
    return { ok, status: ok ? 200 : 500, statusText: "broken", json: async () => ({ state: "planning", counts: {} }) } as Response;
  }));
  return calls;
}

describe("DataChooser", () => {
  it("offers the three choices, with what each costs, as a dialog", () => {
    serve();
    render(<DataChooser onChosen={() => undefined} />);
    expect(screen.getByRole("dialog", { name: /how much race data/i })).toBeDefined();
    expect(screen.getAllByRole("button").map((b) => b.querySelector(".chooser-title")?.textContent))
      .toEqual(["The last 5 races", "The latest whole season", "Everything since 2023"]);
    expect(screen.getByText(/About 24 hours/)).toBeDefined();
  });

  it("saves what was picked, and only then goes away", async () => {
    const calls = serve();
    const onChosen = vi.fn();
    render(<DataChooser onChosen={onChosen} />);
    fireEvent.click(screen.getByRole("button", { name: /latest whole season/i }));
    await waitFor(() => expect(onChosen).toHaveBeenCalledOnce());
    expect(calls).toContain("POST /api/data-choice?choice=season");
  });

  it("stays and says so when the choice could not be saved", async () => {
    serve(false);
    const onChosen = vi.fn();
    render(<DataChooser onChosen={onChosen} />);
    fireEvent.click(screen.getByRole("button", { name: /last 5 races/i }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toMatch(/Could not start/));
    expect(onChosen).not.toHaveBeenCalled();
  });
});
