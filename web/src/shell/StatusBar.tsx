import type { SessionInfo } from "../api";
import { DataSources } from "../panels/DataSources";
import { SyncButton } from "../panels/SyncButton";

/**
 * The thin bar at the very bottom: what the app is working from (how many
 * sessions, this one's sources), the data refresh, and where it is served.
 * "Local only" is read from the page's own address, so it is never claimed
 * when the server was opened to the network on purpose.
 */
export function StatusBar({ sessions, info, onSynced }: { sessions: number; info: SessionInfo | null; onSynced: () => void }) {
  const host = typeof window === "undefined" ? "" : window.location.hostname;
  const local = host === "127.0.0.1" || host === "localhost" || host === "";
  return (
    <footer className="status-bar">
      <span className="status-item"><span className="status-dot" aria-hidden="true" />{sessions} sessions</span>
      {info && <DataSources sources={info.sources} />}
      <span className="status-item">Models never see the race they are asked about</span>
      <span className="bar-spacer" />
      <SyncButton onSynced={onSynced} />
      <span className="status-item" title={local ? "The server answers this computer only" : `Served at ${host}`}>
        {local ? "Local only" : `Shared: ${host}`}
      </span>
    </footer>
  );
}
