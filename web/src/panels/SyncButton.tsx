import { useCallback, useEffect, useRef, useState } from "react";
import { api, type SyncStatus } from "../api";

interface Props {
  /** Called once when a sync has written new sessions, so the list can be read again. */
  onSynced: () => void;
  /** How often to ask how a running sync is going. */
  pollMs?: number;
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
 */
export function SyncButton({ onSynced, pollMs = 2000 }: Props) {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const wasRunning = useRef(false);

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

  // Poll while a sync runs; when it ends having written something, say so once.
  useEffect(() => {
    if (!running) {
      if (wasRunning.current && status?.state === "done" && (status.counts.written ?? 0) > 0) {
        onSynced();
      }
      wasRunning.current = false;
      return;
    }
    wasRunning.current = true;
    const timer = setInterval(() => void read(), pollMs);
    return () => clearInterval(timer);
  }, [running, status, read, pollMs, onSynced]);

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
