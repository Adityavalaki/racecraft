import type { ReactNode } from "react";
import { RAIL_GROUPS, SCREENS, type ScreenId } from "../features";
import { SyncButton } from "../panels/SyncButton";

interface Props {
  screen: ScreenId;
  onScreen: (screen: ScreenId) => void;
  onSynced: () => void;
}

/** Line icons for the rail, one per screen, drawn at 20 px. */
const ICONS: Record<ScreenId, ReactNode> = {
  replay: <><circle cx="12" cy="12" r="8.5" /><path d="M10 8.5v7l6-3.5z" /></>,
  tower: <path d="M4 6h16M4 12h16M4 18h10" />,
  trace: <path d="M3 19h18M3 15l5-5 4 3 4-7 5 4" />,
  pedals: <path d="M3 17l4-6 3 3 4-8 3 5 4-2" />,
  strategy: <path d="M5 20V4M5 5h11l-2 3.5 2 3.5H5" />,
  tyres: <><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="3" /></>,
  prediction: <path d="M4 19h16M7 19v-6M12 19V6M17 19v-9" />,
  stewards: <path d="M12 4l7 3v5c0 4-3 7-7 8-4-1-7-4-7-8V7z" />,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1" /></>,
};

export function ScreenIcon({ id }: { id: ScreenId }) {
  return (
    <svg className="rail-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[id]}
    </svg>
  );
}

/** The brand mark: a red wedge with the trace line through it. */
export function BrandMark({ size = 30 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 30 30" fill="none" aria-hidden="true">
      <path d="M8 3h22l-8 24H0z" fill="var(--signal)" />
      <path d="M6 21 L11 13 L15 18 L19 9 L23 15" stroke="#FFFFFF" strokeWidth="2.4" strokeLinecap="round"
            strokeLinejoin="round" />
    </svg>
  );
}

/**
 * The navigation rail: every screen, grouped as a race engineer would (the
 * race as it runs, the plan, race control), with refreshing the data and the
 * settings at its foot. The screen on show is marked for assistive technology
 * as well as by eye.
 */
export function Rail({ screen, onScreen, onSynced }: Props) {
  const item = (id: ScreenId, title: string) => (
    <button key={id} type="button" className={`rail-item${screen === id ? " is-current" : ""}`}
            aria-current={screen === id ? "page" : undefined} onClick={() => onScreen(id)}>
      <ScreenIcon id={id} />
      <span>{title}</span>
    </button>
  );
  return (
    <aside className="rail" aria-label="Racecraft navigation">
      <button type="button" className="rail-brand" onClick={() => onScreen("replay")} aria-label="Racecraft: back to the replay">
        <BrandMark />
        <span className="display">RACECRAFT</span>
      </button>
      <nav className="rail-nav" aria-label="Screens">
        {RAIL_GROUPS.map((group) => (
          <div key={group} className="rail-group" role="group" aria-label={group}>
            <span className="rail-group-label">{group}</span>
            {SCREENS.filter((s) => s.group === group).map((s) => item(s.id, s.title))}
          </div>
        ))}
      </nav>
      <div className="rail-foot">
        <SyncButton onSynced={onSynced} />
        {item("settings", "Settings")}
      </div>
    </aside>
  );
}
