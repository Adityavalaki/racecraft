import { memo, type ReactNode } from "react";
import type { Insight, LapSeries, RaceControlEvent, SessionInfo, SessionState } from "../api";
import { screenById, type ScreenId } from "../features";
import { PredictionBoard } from "../panels/PredictionBoard";
import { ScreenHeader } from "../shell/ScreenHeader";
import { PedalsScreen } from "./PedalsScreen";
import { TowerScreen } from "./TowerScreen";
import { StewardsScreen } from "./StewardsScreen";
import { StrategyScreen } from "./StrategyScreen";
import { TraceScreen } from "./TraceScreen";
import { TyresScreen } from "./TyresScreen";

/** Everything a screen may read: the session, the clock's moment, and what to do on a click. */
export interface ScreenContext {
  session: string;
  t: number;
  info: SessionInfo;
  state: SessionState | null;
  laps: LapSeries[];
  /** When the leader finished each lap, to place a time on the lap chart. */
  crossings: { laps: number[]; t: number[] } | null;
  selected: number[];
  onSelect: (driver: number) => void;
  onSelectLap: (lap: number) => void;
  insight: Insight | null;
  insightError: string | null;
  actualStops: number | null;
  sessionBest: number | null;
  stewards: RaceControlEvent[];
  trackLog: RaceControlEvent[];
  driverCodes: Record<number, string>;
  /** The session picker in the main window; the session's name in a pop-out. */
  picker?: ReactNode;
  /** Present in the main window: opens this screen in a window of its own. */
  onPopOut?: () => void;
  /** Anything else the window keeps in the header, like a pop-out's sync state. */
  extra?: ReactNode;
}

/** The screens that need the strategy model's fit of the season. */
export const NEEDS_INSIGHT = new Set<ScreenId>(["tyres", "strategy"]);

/**
 * One screen, header and all, the same in the main window and in a window of
 * its own. The replay is not here: it is the main window's own.
 */
export const ScreenView = memo(function ScreenView({ id, ctx }: { id: Exclude<ScreenId, "replay" | "settings">; ctx: ScreenContext }) {
  const screen = screenById(id)!;
  const header = (children?: ReactNode) => (
    <ScreenHeader title={screen.title} hint={screen.hint} picker={ctx.picker} onPopOut={ctx.onPopOut}>
      {children}
      {ctx.extra}
    </ScreenHeader>
  );
  switch (id) {
    case "pedals":
      return <PedalsScreen ctx={ctx} header={header} />;
    case "tower":
      return <TowerScreen ctx={ctx} header={header} />;
    case "trace":
      return <TraceScreen ctx={ctx} header={header} />;
    case "strategy":
      return <StrategyScreen ctx={ctx} header={header} />;
    case "tyres":
      return <TyresScreen ctx={ctx} header={header} />;
    case "prediction":
      return (
        <div className="screen">
          {header()}
          <main className="screen-body">
            <section className="panel">
              <PredictionBoard sessionKey={ctx.session} selected={ctx.selected} onSelect={ctx.onSelect} />
            </section>
          </main>
        </div>
      );
    case "stewards":
      return <StewardsScreen ctx={ctx} header={header} />;
  }
});
