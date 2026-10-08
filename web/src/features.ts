/**
 * The screens, as the navigation rail lists them.
 *
 * Every screen shows in the main window, picked from the rail. All but the
 * replay and settings can also pop out into a window of its own, for a second
 * monitor: the desktop app makes those windows itself (POST /api/app/window,
 * see src/racecraft/app/windows.py, which keeps the same list of ids); a plain
 * browser opens a tab or popup instead. Either way the window loads this app
 * with `?feature=` and follows the main window's clock (see sync.ts).
 */

export type ScreenId =
  | "replay" | "tower" | "trace" | "pedals" | "strategy" | "tyres" | "prediction" | "stewards" | "settings";

/** The screens that can have a window of their own. */
export type FeatureId = Exclude<ScreenId, "replay" | "settings">;

export type ScreenGroup = "Race" | "Plan" | "Control";

export interface Screen {
  id: ScreenId;
  title: string;
  /** One line under the title, saying what the screen is for. */
  hint: string;
  group: ScreenGroup | null;
  /** Can pop out into a window of its own. */
  poppable: boolean;
}

export const SCREENS: readonly Screen[] = [
  { id: "replay", title: "Replay", hint: "The race on the map, with the cars you follow.", group: "Race", poppable: false },
  { id: "tower", title: "Timing tower", hint: "Every car, every lap and sector, in race order.", group: "Race", poppable: true },
  { id: "trace", title: "Race trace", hint: "How the gaps opened and closed, lap by lap.", group: "Race", poppable: true },
  { id: "pedals", title: "Pedals and speed", hint: "Where each driver brakes, lifts and gets back on the throttle.", group: "Race", poppable: true },
  { id: "strategy", title: "Strategy", hint: "When each car is likely to stop, and who can jump a place.", group: "Plan", poppable: true },
  { id: "tyres", title: "Tyres", hint: "How fast each compound fades, and where every car sits on that curve.", group: "Plan", poppable: true },
  { id: "prediction", title: "Race prediction", hint: "The race, called from Friday and Saturday. Chances, not certainties.", group: "Plan", poppable: true },
  { id: "stewards", title: "Stewards", hint: "Every race control message, with what it means for the result.", group: "Control", poppable: true },
  { id: "settings", title: "Settings", hint: "How Racecraft looks, and where its data comes from.", group: null, poppable: false },
];

export const RAIL_GROUPS: readonly ScreenGroup[] = ["Race", "Plan", "Control"];

export function screenById(id: string | null | undefined): Screen | undefined {
  return SCREENS.find((screen) => screen.id === id);
}

/** A screen that can be a window of its own, or undefined. */
export function featureById(id: string | null | undefined): (Screen & { id: FeatureId }) | undefined {
  const screen = screenById(id);
  return screen?.poppable ? (screen as Screen & { id: FeatureId }) : undefined;
}

/** The URL a feature window loads. */
export function featureUrl(id: FeatureId, session: string): string {
  return `/?${new URLSearchParams({ feature: id, session }).toString()}`;
}

/**
 * Open a screen in a window of its own, or bring forward the one already
 * showing it.
 *
 * Asks the desktop app first. A server without that route (racecraft-serve in
 * a browser) answers 404, and the browser opens it instead, under a name per
 * feature, so asking twice reuses the same window rather than stacking them.
 */
export async function openFeature(id: FeatureId, session: string): Promise<"app" | "browser"> {
  try {
    const query = new URLSearchParams({ feature: id, session }).toString();
    const response = await fetch(`/api/app/window?${query}`, { method: "POST" });
    if (response.ok) return "app";
  } catch {
    // No server answer at all: the browser can still open it.
  }
  const opened = window.open(featureUrl(id, session), `racecraft-${id}`, "width=1280,height=860");
  opened?.focus();
  return "browser";
}
