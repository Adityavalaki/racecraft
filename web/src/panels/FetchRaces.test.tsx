import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FetchRaces } from "./FetchRaces";
import type { IngestStatus } from "../api";

/**
 * The control exists so that keeping a deployed Racecraft current does not mean
 * opening a shell on the machine it runs on. What it has to get right is
 * telling the truth while it works: ingesting a weekend takes minutes, and two
 * minutes of silence reads as broken however well it is going.
 */
function status(overrides: Partial<IngestStatus> = {}): IngestStatus {
  return {
    running: false, started_at: null, finished_at: null, season: 2026,
    total: 0, done: 0, written: 0, skipped: 0, failed: 0,
    current: null, error: null, log: [], lake_bytes: 23_000_000,
    ...overrides,
  };
}

function mock(responses: { get?: IngestStatus[]; post?: IngestStatus; postFails?: string }) {
  const queue = [...(responses.get ?? [status()])];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") {
      if (responses.postFails) {
        return { ok: false, json: async () => ({ detail: responses.postFails }) } as Response;
      }
      return { ok: true, json: async () => responses.post ?? status({ running: true }) } as Response;
    }
    const next = queue.length > 1 ? queue.shift()! : queue[0]!;
    return { ok: true, json: async () => next } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("FetchRaces", () => {
  it("offers to fetch when nothing is running", async () => {
    mock({});
    render(<FetchRaces onFinished={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("button", { name: /fetch new races/i })).toBeDefined());
  });

  it("shows how far it has got, not just that it is busy", async () => {
    mock({ get: [status({ running: true, total: 5, done: 2, current: "Azerbaijan Grand Prix R" })] });
    render(<FetchRaces onFinished={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/2\/5/)).toBeDefined());
    expect(screen.getByText("Azerbaijan Grand Prix R")).toBeDefined();
  });

  it("reports failures beside successes rather than only the good news", async () => {
    mock({ get: [status({ running: true, total: 3, done: 3, written: 2, failed: 1, skipped: 0 })] });
    render(<FetchRaces onFinished={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("written")).toBeDefined());
    const failed = screen.getByText("failed").closest("span");
    expect(failed?.className).toContain("is-bad");
  });

  it("reloads the session list once a fetch has added something", async () => {
    const onFinished = vi.fn();
    mock({
      get: [
        status({ running: true, total: 1, done: 0 }),
        status({ running: false, total: 1, done: 1, written: 1 }),
      ],
      post: status({ running: true, total: 1 }),
    });
    render(<FetchRaces onFinished={onFinished} />);

    screen.getByRole("button", { name: /fetch new races/i }).click();
    // The newest race is the one someone came to look at, so the list cannot
    // wait until the next reload to show it.
    await waitFor(() => expect(onFinished).toHaveBeenCalled(), { timeout: 5000 });
  });

  it("does not reload the list when a fetch found nothing new", async () => {
    const onFinished = vi.fn();
    mock({
      get: [
        status({ running: true }),
        status({ running: false, total: 0, written: 0, log: ["nothing new in 2026"] }),
      ],
      post: status({ running: true }),
    });
    render(<FetchRaces onFinished={onFinished} />);
    screen.getByRole("button", { name: /fetch new races/i }).click();

    await waitFor(() => expect(screen.getByText(/nothing new/)).toBeDefined(), { timeout: 5000 });
    expect(onFinished).not.toHaveBeenCalled();
  });

  it("says why when a second fetch is refused", async () => {
    mock({ postFails: "an ingest is already running" });
    render(<FetchRaces onFinished={vi.fn()} />);

    screen.getByRole("button", { name: /fetch new races/i }).click();
    await waitFor(() => expect(screen.getByText("an ingest is already running")).toBeDefined());
  });

  it("shows the log, so a long wait is visibly progress and not a hang", async () => {
    mock({
      get: [status({
        running: true, total: 2, done: 1,
        log: ["12:00:01  2 new sessions in 2026", "12:04:12  Azerbaijan Grand Prix R: written"],
      })],
    });
    render(<FetchRaces onFinished={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/Azerbaijan Grand Prix R: written/)).toBeDefined());
  });
});
