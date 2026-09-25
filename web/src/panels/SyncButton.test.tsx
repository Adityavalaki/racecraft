import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SyncButton } from "./SyncButton";
import type { SyncStatus } from "../api";

/**
 * The sync takes minutes, so what the button must get right is the wait: say
 * what it is doing while it works, say what it did when it stops, and ask for
 * the session list again only when there is something new in it.
 */
function status(overrides: Partial<SyncStatus> = {}): SyncStatus {
  return {
    state: "idle", weekends: [], items: [], counts: {}, to_fetch: 0, current: null,
    started_at: null, finished_at: null, error: null, ...overrides,
  };
}

const WEEKENDS = ["2026 Hungarian Grand Prix", "2026 Dutch Grand Prix", "2026 Italian Grand Prix",
                  "2026 Spanish Grand Prix", "2026 Azerbaijan Grand Prix"];

/** GETs answer from `reads` in order (the last one repeats); POST answers `started`. */
function serve(reads: SyncStatus[], started: SyncStatus = status({ state: "planning" })) {
  let index = 0;
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    const body = init?.method === "POST" ? started : reads[Math.min(index++, reads.length - 1)];
    return { ok: true, json: async () => body } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("SyncButton", () => {
  it("offers to sync and says nothing until asked", async () => {
    serve([status()]);
    render(<SyncButton onSynced={() => undefined} />);
    expect(screen.getByRole("button", { name: /sync latest 5/i })).toBeDefined();
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe(""));
  });

  it("names the session it is fetching while it works", async () => {
    serve([status({
      state: "running", weekends: WEEKENDS, to_fetch: 3, counts: { written: 1 },
      current: "Azerbaijan Grand Prix Practice 2",
    })]);
    render(<SyncButton onSynced={() => undefined} pollMs={10} />);
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toBe("fetching 2 of 3 · Azerbaijan Grand Prix Practice 2"));
    const button = screen.getByRole("button") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
  });

  it("reads the session list again when new sessions land, and only once", async () => {
    const fetchMock = serve([
      status(),
      status({ state: "running", weekends: WEEKENDS, to_fetch: 2, current: "Azerbaijan Grand Prix Practice 2" }),
      status({ state: "done", weekends: WEEKENDS, to_fetch: 2, counts: { written: 2 } }),
    ]);
    const onSynced = vi.fn();
    render(<SyncButton onSynced={onSynced} pollMs={10} />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    fireEvent.click(screen.getByRole("button", { name: /sync latest 5/i }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("added 2 sessions"));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(onSynced).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit | undefined)?.method === "POST"))
      .toBe(true);
  });

  it("says it is up to date, and leaves the list alone, when there was nothing to fetch", async () => {
    serve([
      status(),
      status({ state: "done", weekends: WEEKENDS, to_fetch: 0, counts: { present: 21 } }),
    ], status({ state: "running", weekends: WEEKENDS }));
    const onSynced = vi.fn();
    render(<SyncButton onSynced={onSynced} pollMs={10} />);
    fireEvent.click(screen.getByRole("button", { name: /sync latest 5/i }));
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("up to date · 5 weekends"));
    expect(onSynced).not.toHaveBeenCalled();
  });

  it("owns up to a session it could not fetch, with the reason on hover", async () => {
    serve([status({
      state: "done", weekends: WEEKENDS, to_fetch: 2, counts: { written: 1, failed: 1 },
      items: [{ key: "2026_15_FP2", season: 2026, round: 15, ident: "FP2", event: "Azerbaijan Grand Prix",
                name: "Practice 2", state: "failed", detail: "NoLapDataError: not published yet" }],
    })]);
    render(<SyncButton onSynced={() => undefined} />);
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("added 1 session, 1 failed"));
    expect(screen.getByRole("status").getAttribute("title")).toContain("not published yet");
  });
});

describe("SyncButton, when another process has a session", () => {
  it("says it is being fetched elsewhere rather than calling it done", async () => {
    serve([status({
      state: "done", weekends: WEEKENDS, to_fetch: 1, counts: { busy: 1 },
      items: [{ key: "2026_15_FP2", season: 2026, round: 15, ident: "FP2", event: "Azerbaijan Grand Prix",
                name: "Practice 2", state: "busy", detail: "another process is fetching it" }],
    })]);
    render(<SyncButton onSynced={() => undefined} />);
    await waitFor(() => expect(screen.getByRole("status").textContent).toBe("1 still being fetched elsewhere"));
    expect(screen.getByRole("status").getAttribute("title")).toContain("another process is fetching it");
  });
});
