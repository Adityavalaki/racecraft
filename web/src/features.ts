/**
 * The analysis features, each of which opens in a window of its own.
 *
 * The desktop app makes those windows itself (POST /api/app/window, see
 * src/racecraft/app/windows.py, which keeps the same list of ids); a plain
 * browser opens a tab or popup instead. Either way the window loads this app
 * with `?feature=` and follows the replay window's clock (see sync.ts).
 */

export type FeatureId = "tower" | "trace" | "tyres" | "strategy" | "sets" | "stewards" | "track";

export interface Feature {
  id: FeatureId;
  title: string;
  /** One line on what it shows, for the launcher and the window's header. */
  hint: string;
}

export const FEATURES: readonly Feature[] = [
  { id: "tower", title: "Timing tower", hint: "every car: gaps, best and last laps, sectors, tyres, pits, penalties" },
  { id: "trace", title: "Race trace", hint: "gap to the lap leader, lap by lap · click to jump" },
  { id: "tyres", title: "Tyre model", hint: "modelled wear against what this race did" },
  { id: "strategy", title: "Strategy", hint: "cheapest plans, and what they ignore" },
  { id: "sets", title: "Tyre sets", hint: "every car's sets · follows the clock" },
  { id: "stewards", title: "Stewards", hint: "verdicts, investigations and penalties" },
  { id: "track", title: "Track log", hint: "flags, safety car, pit exit and conditions" },
];

export function featureById(id: string | null | undefined): Feature | undefined {
  return FEATURES.find((feature) => feature.id === id);
}

/** The URL a feature window loads. */
export function featureUrl(id: FeatureId, session: string): string {
  return `/?${new URLSearchParams({ feature: id, session }).toString()}`;
}

/**
 * Open a feature's window, or bring forward the one already showing it.
 *
 * Asks the desktop app first. A server without that route (racecraft-serve in
 * a browser) answers 404, and the browser opens it instead — under a name per
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
  const opened = window.open(featureUrl(id, session), `racecraft-${id}`, "width=1100,height=760");
  opened?.focus();
  return "browser";
}
