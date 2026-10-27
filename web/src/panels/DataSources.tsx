import type { SessionInfo } from "../api";

/** The sources credited by name; anything else (corners copied from an earlier session) is in the tooltip only. */
const NAMED = ["FastF1", "F1 live timing", "OpenF1", "Jolpica", "TracingInsights"];

/**
 * Where this session's data came from, beside the session picker: the sources by
 * name, and each table's own in the tooltip. Since F1's archive wants an F1 TV
 * login, a session can be built from several free sources (D-009 step 5).
 */
export function DataSources({ sources }: { sources: SessionInfo["sources"] }) {
  if (!sources?.length) return null;
  const names = NAMED.filter((name) => sources.some((s) => s.source.split(" + ").includes(name)));
  if (!names.length) return null;
  const detail = sources.map((s) => `${s.table_name === "all" ? "every table" : s.table_name}: ${s.source}`).join("\n");
  return (
    <span className="session-sources" title={detail}>
      Data: {names.join(" · ")}
    </span>
  );
}
