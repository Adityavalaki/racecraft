import { useCallback, useEffect, useRef, useState } from "react";
import { api, type SyncStatus } from "../api";

interface Props {
  /** Called once when a sync has written new sessions, so the list can be read again. */
  onSynced: () => void;
  /** How often to ask how a running sync is going. */
  pollMs?: number;
  /**
   * How often to look when nothing is running. The desktop app syncs by itself
   * every fifteen minutes, and this is how the button finds out.
   */
  idlePollMs?: number;
}

const RUNNING = new Set(["planning", "running"]);

/**
 * Bring the latest five race weekends into the lake.
 *
 * The server does the work in the background — it checks which published
 * sessions are missing and ingests only those — and this button reports how
 * it is going. It reads the status on mount as well as after a click, so a
 * sync started in another tab, or before a reload, still shows here.
 *
 * Ingesting a session takes about a minute, so the label names the session in
 * hand rather than spinning: a long wait that says what it is doing reads as
 * working, not as stuck.
 *
 * It also notices syncs it did not start — the desktop app runs one every
 * fifteen minutes — by looking now and then while idle, and treats a sync as
 * news when its finish time is one it has not seen, not only when it watched
 * the sync run. A short automatic sync can start and end between two looks.
 */
export function SyncButton({ onSynced, pollMs = 2000, idlePollMs = 30_000 }: Props) {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The finish time of the last sync already accounted for. Undefined until the
  // first read, whose finished sync is history rather than news.
  const seenFinish = useRef<string | null | undefined>(undefined);

  const read = useCallback(async () => {
    try {
      const next = await api.syncStatus();
      // A server without the sync endpoint answers something else entirely;
      // one button must not take the page down with it.
      if (!isStatus(next)) throw new Error("the server does not offer a sync");
      setStatus(next);
      setError(null);
      return next;
    } catch (e) {
      setError(String((e as Error).message ?? e));
      return null;
    }
  }, []);

  useEffect(() => {
    void read();
  }, [read]);

  const running = status !== null && RUNNING.has(status.state);

  // Often while a sync runs, now and then while idle.
  useEffect(() => {
    const timer = setInterval(() => void read(), running ? pollMs : idlePollMs);
    return () => clearInterval(timer);
  }, [running, read, pollMs, idlePollMs]);

  // A sync that finished since the last look and wrote something: say so once.
  useEffect(() => {
    if (!status) return;
    if (status.state !== "done" && status.state !== "failed") {
      if (seenFinish.current === undefined) seenFinish.current = null;
      return;
    }
    if (seenFinish.current === undefined) {
      seenFinish.current = status.finished_at;
      return;
    }
    if (status.finished_at !== seenFinish.current) {
      seenFinish.current = status.finished_at;
      if ((status.counts.written ?? 0) > 0) onSynced();
    }
  }, [status, onSynced]);

  const start = async () => {
    try {
      const next = await api.sync();
      if (!isStatus(next)) throw new Error("the server does not offer a sync");
      setStatus(next);
      setError(null);
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  return (
    <div className="sync">
      <button type="button" className="sync-button" onClick={start} disabled={running}
              title="Fetch any session from the latest five race weekends that is not in the lake yet">
        {running ? "Syncing…" : "Sync latest 5"}
      </button>
      <span className="sync-status" role="status" title={detailOf(status, error)}>
        {summaryOf(status, error)}
      </span>
    </div>
  );
}

function isStatus(value: unknown): value is SyncStatus {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    && typeof (value as SyncStatus).state === "string" && typeof (value as SyncStatus).counts === "object";
}

function summaryOf(status: SyncStatus | null, error: string | null): string {
  if (error) return "sync unavailable";
  if (!status || status.state === "idle") return "";
  if (status.state === "planning") return "checking the calendar…";
  if (status.state === "failed") return "sync failed";

  const written = status.counts.written ?? 0;
  const failed = status.counts.failed ?? 0;
  const busy = status.counts.busy ?? 0;
  if (status.state === "running") {
    const done = written + failed;
    return status.current
      ? `fetching ${done + 1} of ${status.to_fetch} · ${status.current}`
      : `${done} of ${status.to_fetch} fetched`;
  }
  // done
  const parts = [];
  if (written) parts.push(`added ${written} session${written === 1 ? "" : "s"}`);
  if (busy) parts.push(`${busy} still being fetched elsewhere`);
  if (failed) parts.push(`${failed} failed`);
  return parts.length ? parts.join(", ") : `up to date · ${status.weekends.length} weekends`;
}

function detailOf(status: SyncStatus | null, error: string | null): string {
  if (error) return error;
  if (!status) return "";
  if (status.error) return status.error;
  const failed = status.items.filter((item) => item.state === "failed" || item.state === "busy");
  const lines = [status.weekends.join(", ")];
  for (const item of failed) lines.push(`${item.event} ${item.name}: ${item.detail}`);
  return lines.filter(Boolean).join("\n");
}
