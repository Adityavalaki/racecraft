import { useCallback, useEffect, useRef, useState } from "react";
import { api, type IngestStatus } from "../api";

interface Props {
  /** Called when an ingest finishes having written something, so the list can reload. */
  onFinished: () => void;
}

const POLL_MS = 2000;

/**
 * Fetching new races without a terminal.
 *
 * A deployed Racecraft is no use if keeping it current means opening a shell on
 * the machine it runs on. This is the alternative: a control that says what it
 * is doing while it does it.
 *
 * It polls rather than streams, because ingesting a weekend takes minutes —
 * FastF1 allows 500 requests an hour and ingest waits rather than tripping the
 * limit — and a connection held open that long is lost to the first proxy
 * timeout between here and the server.
 *
 * Progress is shown as it happens rather than summarised at the end, for the
 * same reason a long silence is worse than a slow answer: after two minutes of
 * nothing, the only honest reading is that it has broken.
 */
export function FetchRaces({ onFinished }: Props) {
  const [status, setStatus] = useState<IngestStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const wasRunning = useRef(false);

  const poll = useCallback(async () => {
    try {
      const next = await api.ingestStatus();
      setStatus(next);
      // The moment it stops, not a poll later: the session list is stale until
      // it reloads, and the newest race is the one someone came to look at.
      if (wasRunning.current && !next.running) {
        wasRunning.current = false;
        if (next.written > 0) onFinished();
      }
      if (next.running) wasRunning.current = true;
      return next.running;
    } catch (e) {
      setError(String((e as Error).message ?? e));
      return false;
    }
  }, [onFinished]);

  useEffect(() => {
    void poll();
  }, [poll]);

  useEffect(() => {
    if (!status?.running) return;
    const timer = setInterval(() => void poll(), POLL_MS);
    return () => clearInterval(timer);
  }, [status?.running, poll]);

  const start = async () => {
    setError(null);
    setOpen(true);
    try {
      setStatus(await api.ingestStart());
      wasRunning.current = true;
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  const running = status?.running ?? false;
  const showPanel = open || running;

  return (
    <div className="fetch">
      <button
        type="button"
        className="fetch-button"
        onClick={running ? () => setOpen((v) => !v) : start}
        aria-busy={running}
      >
        {running ? `Fetching… ${status?.done ?? 0}/${status?.total ?? 0}` : "Fetch new races"}
      </button>

      {showPanel && (
        <div className="fetch-panel" role="status" aria-live="polite">
          <div className="fetch-head">
            <span>{running ? status?.current ?? "starting" : "Last fetch"}</span>
            <button type="button" className="fetch-close" onClick={() => setOpen(false)}>
              close
            </button>
          </div>

          {error && <p className="fetch-error">{error}</p>}

          {status && (
            <>
              {status.total > 0 && (
                <div className="fetch-bar" aria-label={`${status.done} of ${status.total}`}>
                  <i style={{ width: `${(status.done / Math.max(1, status.total)) * 100}%` }} />
                </div>
              )}
              <div className="fetch-counts">
                <span><b>{status.written}</b> written</span>
                <span><b>{status.skipped}</b> already here</span>
                <span className={status.failed ? "is-bad" : ""}><b>{status.failed}</b> failed</span>
                <span className="fetch-size">{(status.lake_bytes / 1e6).toFixed(0)} MB</span>
              </div>
              {status.log.length > 0 && (
                <ol className="fetch-log">
                  {status.log.slice(-8).map((line, index) => (
                    <li key={`${index}-${line}`}>{line}</li>
                  ))}
                </ol>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
