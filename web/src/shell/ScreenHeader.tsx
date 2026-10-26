import type { ReactNode } from "react";
import type { SessionSummary } from "../api";

/** The session list as a picker, grouped by season, newest first as the list comes. */
export function SessionPicker({ sessions, value, onChange }: {
  sessions: SessionSummary[];
  value: string | null;
  onChange: (key: string) => void;
}) {
  const years = [...new Set(sessions.map((s) => s.year))];
  return (
    <label className="session-picker">
      <span className="visually-hidden">Session</span>
      <select value={value ?? ""} onChange={(event) => onChange(event.target.value)} aria-label="Choose a session">
        {years.map((year) => (
          <optgroup key={year} label={String(year)}>
            {sessions.filter((s) => s.year === year).map((s) => (
              <option key={s.session_key} value={s.session_key}>
                R{String(s.round).padStart(2, "0")} · {s.event_name} · {s.session_name}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
        <path d="M3 5 L7 9 L11 5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </label>
  );
}

/** Opens the screen in a window of its own, for a second monitor. */
export function PopOutButton({ onPopOut, label }: { onPopOut: () => void; label: string }) {
  return (
    <button type="button" className="pop-out" onClick={onPopOut} aria-label={`Open ${label} in a window of its own`}
            title="Open in a window of its own">
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" aria-hidden="true">
        <path d="M4 2.5h5.5V8M9.5 2.5 3 9" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </button>
  );
}

/**
 * A screen's title bar: the name in the display face with the red slash,
 * the line saying what it is for, the session, and whatever else the screen
 * keeps up there (the lap, a mode switch), with the pop-out button last.
 */
export function ScreenHeader({ title, hint, picker, children, onPopOut }: {
  title: string;
  hint: string;
  picker?: ReactNode;
  children?: ReactNode;
  onPopOut?: () => void;
}) {
  return (
    <header className="screen-header">
      <div className="screen-title">
        <h1 className="display"><span className="title-slash" aria-hidden="true" />{title}</h1>
        <span className="screen-hint">{hint}</span>
      </div>
      {picker}
      <div className="screen-actions">
        {children}
        {onPopOut && <PopOutButton onPopOut={onPopOut} label={title} />}
      </div>
    </header>
  );
}

/** The lap, big: "Lap 16 / 51". */
export function LapCounter({ lap, total }: { lap: number; total: number | null }) {
  return (
    <div className="lap-counter" aria-label={`Lap ${lap}${total ? ` of ${total}` : ""}`}>
      <span className="lap-label">Lap</span>
      <span className="display lap-now">{lap}</span>
      {total ? <span className="display lap-total">/ {total}</span> : null}
    </div>
  );
}
