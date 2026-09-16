export interface SessionSummary {
  session_key: string;
  year: number;
  round: number;
  session: string;
  event_name: string;
  location: string;
  session_name: string;
  date_utc: string;
  total_laps: number | null;
}

export interface Driver {
  driver_number: number;
  abbreviation: string | null;
  full_name: string | null;
  team_name: string | null;
  team_color: string | null;
  grid_position: number | null;
  position: number | null;
  classified_position: string | null;
  status: string | null;
}

export interface SessionInfo {
  session: Record<string, unknown> & { event_name: string; session_name: string; location: string };
  t_start: number;
  t_end: number;
  total_laps: number | null;
  drivers: Driver[];
  outline: [number, number][];
  bounds: { min_x: number; max_x: number; min_y: number; max_y: number } | Record<string, never>;
  has_position_data: boolean;
}

export interface DriverTiming {
  driver_number: number;
  abbreviation: string | null;
  team_name: string | null;
  team_color: string | null;
  position: number;
  status: "racing" | "out" | "finished" | "not_started";
  laps_completed: number;
  gap_to_leader_s: number | null;
  gap_text: string;
  interval_s: number | null;
  interval_text: string;
  laps_down: number;
  last_lap_s: number | null;
  best_lap_s: number | null;
  is_session_best: boolean;
  is_personal_best: boolean;
  compound: string | null;
  tyre_life: number | null;
  laps_in_stint: number | null;
  stops: number;
}

export interface CarState {
  x: number | null;
  y: number | null;
  speed?: number | null;
  gear?: number | null;
  throttle?: number | null;
  brake?: number | null;
  drs?: number | null;
  rpm?: number | null;
}

export interface SessionState {
  t: number;
  leader_lap: number;
  drivers: DriverTiming[];
  cars: Record<string, CarState>;
  track_status: { status: string; message: string } | null;
  weather: { air_temp: number | null; track_temp: number | null; rainfall: boolean | null } | null;
}

export interface Frames {
  t: number[];
  drivers: Record<string, { x: (number | null)[]; y: (number | null)[] }>;
}

export interface LapSeries {
  driver_number: number;
  abbreviation: string | null;
  team_color: string | null;
  laps: number[];
  gap_to_leader_s: (number | null)[];
  lap_time_s: (number | null)[];
  compound: (string | null)[];
  pit_in: boolean[];
}

export interface LapChart {
  drivers: LapSeries[];
  /** When the leader completed each lap, so the clock can jump to a lap exactly. */
  leader_crossings: { laps: number[]; t: number[] };
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(detail.detail ?? `request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export const api = {
  sessions: (signal?: AbortSignal) => get<SessionSummary[]>("/api/sessions", signal),
  info: (key: string, signal?: AbortSignal) => get<SessionInfo>(`/api/sessions/${key}`, signal),
  state: (key: string, t: number, signal?: AbortSignal) =>
    get<SessionState>(`/api/sessions/${key}/state?t=${t.toFixed(2)}`, signal),
  frames: (key: string, start: number, end: number, hz: number, signal?: AbortSignal) =>
    get<Frames>(`/api/sessions/${key}/frames?start=${start.toFixed(2)}&end=${end.toFixed(2)}&hz=${hz}`, signal),
  laps: (key: string, signal?: AbortSignal) =>
    get<LapChart>(`/api/sessions/${key}/laps`, signal),
};

/** 92.608 -> "1:32.608", the way lap times are always written. */
export function formatLapTime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  const minutes = Math.floor(seconds / 60);
  const rest = seconds - minutes * 60;
  return minutes > 0 ? `${minutes}:${rest.toFixed(3).padStart(6, "0")}` : rest.toFixed(3);
}

/** Session time as a clock, for the scrubber. */
export function formatClock(seconds: number): string {
  const sign = seconds < 0 ? "-" : "";
  const total = Math.abs(Math.floor(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return `${sign}${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export const COMPOUND_COLORS: Record<string, string> = {
  SOFT: "#e8323c",
  MEDIUM: "#f2c53d",
  HARD: "#e9eaec",
  INTERMEDIATE: "#43b047",
  WET: "#2f7fd8",
};

/** Track status codes from the feed, as the flag bar shows them. */
export const TRACK_STATUS: Record<string, { label: string; color: string }> = {
  "1": { label: "TRACK CLEAR", color: "#2ecc71" },
  "2": { label: "YELLOW FLAG", color: "#f2c53d" },
  "4": { label: "SAFETY CAR", color: "#f2c53d" },
  "5": { label: "RED FLAG", color: "#e8323c" },
  "6": { label: "VIRTUAL SAFETY CAR", color: "#f2c53d" },
  "7": { label: "VSC ENDING", color: "#f2c53d" },
};
