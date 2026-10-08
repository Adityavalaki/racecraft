import { useCallback, useEffect, useState } from "react";

/**
 * How Racecraft looks, as the Settings screen sets it. Kept in this browser,
 * and shared with the pop-out windows: a change in one window reaches the
 * others through the storage event.
 */
export interface Settings {
  units: "metric" | "imperial";
  density: "comfortable" | "compact";
  /** What the header shows beside the lap counter: the session clock or nothing more. */
  clock: "race" | "lap";
  /** Driver codes on every car on the map, not only the followed ones (L). */
  names: boolean;
  /** DRS zones, or overtake rings from 2026 (D). */
  rings: boolean;
}

export const DEFAULT_SETTINGS: Settings = { units: "metric", density: "comfortable", clock: "race", names: false, rings: true };

const KEY = "racecraft:settings:v1";

export function loadSettings(): Settings {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(KEY) ?? "null");
    if (!raw || typeof raw !== "object") return DEFAULT_SETTINGS;
    const saved = raw as Partial<Record<keyof Settings, unknown>>;
    return {
      units: saved.units === "imperial" ? "imperial" : "metric",
      density: saved.density === "compact" ? "compact" : "comfortable",
      clock: saved.clock === "lap" ? "lap" : "race",
      names: typeof saved.names === "boolean" ? saved.names : DEFAULT_SETTINGS.names,
      rings: typeof saved.rings === "boolean" ? saved.rings : DEFAULT_SETTINGS.rings,
    };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function useSettings() {
  const [settings, setSettings] = useState<Settings>(loadSettings);
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key === KEY) setSettings(loadSettings());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);
  const update = useCallback((change: Partial<Settings>) => {
    setSettings((current) => {
      const next = { ...current, ...change };
      try {
        localStorage.setItem(KEY, JSON.stringify(next));
      } catch {
        // Private windows and blocked storage: the change holds for this window only.
      }
      return next;
    });
  }, []);
  return { settings, update };
}

/** A speed in the chosen units, km/h in the data. */
export function speedIn(kmh: number | null | undefined, units: Settings["units"]): { value: string; unit: string } {
  if (kmh == null || !Number.isFinite(kmh)) return { value: "—", unit: units === "metric" ? "km/h" : "mph" };
  return units === "metric"
    ? { value: String(Math.round(kmh)), unit: "km/h" }
    : { value: String(Math.round(kmh * 0.621371)), unit: "mph" };
}
