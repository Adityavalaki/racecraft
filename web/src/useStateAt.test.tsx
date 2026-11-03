import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { SessionInfo } from "./api";
import { useStateAt } from "./sessionData";

afterEach(() => vi.unstubAllGlobals());

it("never hands one session's state to another, not even for a render", async () => {
  const finished = { t: 9, leader_lap: 57, drivers: [{ driver_number: 1, status: "finished" }] };
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => finished }) as Response));
  const info = { t_start: 0 } as SessionInfo;
  const seen: unknown[] = [];
  const { result, rerender } = renderHook(({ key }) => {
    const state = useStateAt(key, info, 9);
    seen.push([key, state]);
    return state;
  }, { initialProps: { key: "2026_18_R" } });
  await waitFor(() => expect(result.current).not.toBeNull());
  seen.length = 0;
  rerender({ key: "2026_19_R" });
  expect(seen[0]).toEqual(["2026_19_R", null]);                 // the first render of the new session
});
