import { useEffect, useMemo, useRef, useState } from "react";
import type { Driver, SessionSummary } from "../api";
import { SCREENS, type ScreenId } from "../features";

interface Props {
  sessions: SessionSummary[];
  drivers: Driver[];
  onScreen: (id: ScreenId) => void;
  onSession: (key: string) => void;
  onFollow: (driverNumber: number) => void;
  onClose: () => void;
}

interface Item {
  id: string;
  group: "Screens" | "Drivers" | "Sessions";
  label: string;
  detail: string;
  run: () => void;
}

/** How many sessions to list at once: the newest that match. */
const MAX_SESSIONS = 8;

/** True when every word typed appears somewhere in the text, in any order. */
export function matches(text: string, query: string): boolean {
  const hay = text.toLowerCase();
  return query.toLowerCase().split(/\s+/).filter(Boolean).every((word) => hay.includes(word));
}

/**
 * One place to jump anywhere (Ctrl K): a screen, a driver of the open session
 * to follow on the map, or another session. Arrows move, Enter goes, Escape
 * closes. Nothing here changes data; it only does what the rail, the tower and
 * the session picker already do.
 */
export function CommandPalette({ sessions, drivers, onScreen, onSession, onFollow, onClose }: Props) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);

  const items = useMemo(() => {
    const done = (run: () => void) => () => { run(); onClose(); };
    const screens: Item[] = SCREENS.map((s) => ({
      id: `screen:${s.id}`, group: "Screens", label: s.title, detail: s.hint, run: done(() => onScreen(s.id)),
    }));
    const people: Item[] = drivers.map((d) => ({
      id: `driver:${d.driver_number}`, group: "Drivers", label: `${d.abbreviation ?? d.driver_number} · ${d.full_name ?? ""}`,
      detail: `${d.team_name ?? ""} · follow on the map`, run: done(() => onFollow(d.driver_number)),
    }));
    const weekends: Item[] = sessions.map((s) => ({
      id: `session:${s.session_key}`, group: "Sessions",
      label: `${s.year} · R${String(s.round).padStart(2, "0")} ${s.event_name} · ${s.session_name}`, detail: "open",
      run: done(() => onSession(s.session_key)),
    }));
    // Names only: a screen's description is full of everyday words ("every", "where") that would match anything.
    const hit = (item: Item) => !query.trim() || matches(item.label, query);
    return [...screens.filter(hit), ...people.filter(hit), ...weekends.filter(hit).slice(0, MAX_SESSIONS)];
  }, [sessions, drivers, query, onScreen, onSession, onFollow, onClose]);

  useEffect(() => setActive(0), [query]);
  const current = items[Math.min(active, items.length - 1)];

  const onKey = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") { event.preventDefault(); onClose(); }
    else if (event.key === "ArrowDown") { event.preventDefault(); setActive((i) => Math.min(i + 1, items.length - 1)); }
    else if (event.key === "ArrowUp") { event.preventDefault(); setActive((i) => Math.max(i - 1, 0)); }
    else if (event.key === "Enter" && current) { event.preventDefault(); current.run(); }
  };

  return (
    <div className="palette-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="palette" role="dialog" aria-modal="true" aria-label="Search sessions, drivers and screens">
        <label className="palette-search">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
          </svg>
          <span className="visually-hidden">Search</span>
          <input ref={input} value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={onKey}
                 placeholder="Search sessions, drivers, screens" role="combobox" aria-expanded="true"
                 aria-controls="palette-list" aria-activedescendant={current ? `palette-${current.id}` : undefined} />
          <kbd>Esc</kbd>
        </label>
        <ul id="palette-list" className="palette-list" role="listbox" aria-label="Results">
          {items.length === 0 && <li className="palette-empty">Nothing matches “{query}”.</li>}
          {items.map((item, i) => (
            <li key={item.id} id={`palette-${item.id}`} role="option" aria-selected={item === current}
                className={`palette-item${item === current ? " is-active" : ""}${i === 0 || items[i - 1]!.group !== item.group ? " is-first" : ""}`}
                data-group={item.group} onMouseEnter={() => setActive(i)} onClick={item.run}>
              <span className="palette-label">{item.label}</span>
              <span className="palette-detail">{item.detail}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
