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
  sectors: SectorTime[];
}

export interface SectorTime {
  sector: number;
  seconds: number | null;
  state: "session_best" | "personal_best" | "normal" | "none";
}

export interface BestSector {
  sector: number;
  seconds: number | null;
  driver_number: number | null;
  driver: string | null;
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
  best_sectors: BestSector[];
  ideal_lap_s: number | null;
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
  /** Classified position on that lap, from the feed. Null where it is missing. */
  position: (number | null)[];
  lap_time_s: (number | null)[];
  compound: (string | null)[];
  pit_in: boolean[];
}

export interface LapChart {
  drivers: LapSeries[];
  /** When the leader completed each lap, so the clock can jump to a lap exactly. */
  leader_crossings: { laps: number[]; t: number[] };
}

export interface PitLoss {
  circuit: string;
  seconds: number;
  spread_s: number;
  stops: number;
  seasons: number;
}

export interface SafetyCarRisk {
  circuit: string;
  races: number;
  share_of_races: number;
  /** Shrunk toward the league average: this is the one to quote. */
  probability: number;
  periods_per_race: number;
  per_lap: number;
  median_laps_lost: number;
}

export interface CurvePoint {
  age: number;
  /** The model's line at the scale actually used for the plans. */
  model_s: number;
  /** The same line before scaling: what was measured, unadjusted. */
  model_unscaled_s: number;
  /** What this race's tyres did at that age, or null where too few laps ran. */
  observed_s: number | null;
  laps: number;
}

export interface DegradationCurve {
  compound: string;
  points: CurvePoint[];
  observed_to_age: number;
}

export interface Plan {
  plan: string;
  stops: number;
  seconds_lost: number;
  tyre_seconds: number;
  compound_seconds: number;
  pit_seconds: number;
  behind_best_s: number;
  stint_laps: number[];
  stop_laps: number[];
  /** Orders this row stands for: the model cannot tell them apart. */
  orders: string[];
}

/** A plan costed over simulated races that can be neutralised. */
export interface RiskyPlan {
  plan: string;
  stops: number;
  expected_s: number;
  green_s: number;
  best_case_s: number;
  worst_case_s: number;
  /** How often at least one stop fell under a safety car. */
  cheap_stop_share: number;
  stop_laps: number[];
  behind_best_s: number;
}

/** One plan, raced against the whole field many times over. */
export interface PlaceRow {
  plan: string;
  stops: number;
  stop_laps: number[];
  mean_finish: number;
  /** Standard error of the mean finish: most plans sit inside each other's. */
  std_error: number;
  median_finish: number;
  best: number;
  worst: number;
  podium_share: number;
  points_share: number;
  gained: number;
  behind_best: number;
  /** Indistinguishable from the best plan at these run counts. */
  within_noise: boolean;
  expected_s?: number;
  green_s?: number;
}

export interface PlacesAnswer {
  session_key: string;
  grid: number;
  runs: number;
  inputs: {
    circuit: string;
    season: number;
    event_name: string;
    total_laps: number;
    /** Fitted only on races that started before this one. */
    held_out: boolean;
    target_session: string | null;
    cutoff: string | null;
    fitted_on_count: number;
    pit_loss_s: number;
    pit_stops: number;
    periods_per_race: number;
    passes_per_race: number;
    following: {
      measured: boolean;
      penalties: { under_s: number; seconds: number }[];
      races: number;
      detail: string;
    };
    notes: string[];
  };
  study: {
    grid: number;
    plans: PlaceRow[];
    cheapest_in_seconds: string | null;
    best_in_places: string | null;
    field_plan: string;
    field_stop_window: [number, number];
    field_draws: number;
  };
  verdict: {
    cheapest_in_seconds: string;
    best_in_places: string;
    agree: boolean;
    tied: string[];
    price: { plan: string; instead_of: string; extra_seconds: number; places_gained: number } | null;
    bad_plan: { plan: string; extra_seconds: number; places_lost: number } | null;
  };
  omissions: string[];
}

/** {"HARD": "C3", "MEDIUM": "C4", "SOFT": "C5", source}: Pirelli's nomination for a race. */
export interface Compounds {
  HARD: string;
  MEDIUM: string;
  SOFT: string;
  source: string;
}

/** A set a car held at the start of a session, and the laps on it. */
export interface HeldSet {
  set: number;
  laps: number;
}

/** A set fitted during the session, with when each of its laps ended. */
export interface SessionSet {
  set: number;
  compound: string;
  new_at_start: boolean;
  laps_at_start: number;
  /** Run here although the tracker had it handed back: its guess was wrong. */
  thought_returned: boolean;
  runs: { start_t: number | null; lap_end_t: number[] }[];
}

export interface CarSets {
  driver_number: number;
  driver: string;
  team: string;
  stand_ins: string[];
  at_start: Record<string, { new: number; used: HeldSet[] }>;
  returned: { set: number; compound: string; after: string; laps: number }[];
  /** New sets handed back where no used one was left: the compound is a guess. */
  new_returned: Record<string, number>;
  this_session: SessionSet[];
  notes: string[];
}

export interface TyreSets {
  session_key: string;
  session: string;
  event_name: string;
  year: number;
  sessions: string[];
  rules: {
    name: string;
    allocation: Record<string, number>;
    returns: { after: string; sets: number }[];
    q3_returns_soft: boolean;
    extra: Record<string, number>;
    hand_backs_known: boolean;
  };
  returns_so_far: { after: string; sets: number }[];
  /** Which Pirelli compound each label is this weekend, and where that was read. */
  compounds: Compounds | null;
  cars: CarSets[];
  notes: string[];
}

/** Whether one car can run one of the model's plans on the sets it had. */
export interface PlanCheck {
  plan: string;
  feasible: boolean;
  reason: string | null;
  stints: { compound: string; laps: number; set_laps: number }[];
  extra_s: number;
  /** The plan's cost on a green race, on new tyres. */
  green_s: number | null;
  /** The same, on this car's tyres. */
  total_s: number | null;
  /** Behind this car's cheapest plan, on its tyres. */
  behind_best_s: number | null;
}

export interface CarPlanChecks {
  driver: string;
  left: Record<string, { new: number; used: number[] }>;
  plans: PlanCheck[];
}

export interface StintRun {
  compound: string;
  laps: number;
  first_lap: number;
  last_lap: number;
}

export interface DriverStints {
  driver: string;
  driver_number: number;
  stops: number;
  stints: StintRun[];
}

export interface LiveStatus {
  attached: boolean;
  recording: string | null;
  bytes?: number;
  laps?: number;
  drivers?: number;
  session?: { year: number; round: number; name: string };
  built_ago_s?: number | null;
  last_read_ago_s?: number | null;
  error?: string | null;
}

/** The one session key that is not in the lake. */
export const LIVE_KEY = "live";

export interface Insight {
  session_key: string;
  circuit: string;
  event_name: string;
  year: number;
  is_race: boolean;
  total_laps: number | null;
  pit_loss: PitLoss | null;
  safety_car: SafetyCarRisk | null;
  scale: number;
  degradation_measured: Record<string, number>;
  degradation_used: Record<string, number>;
  compound_offset_s: Record<string, number>;
  fuel_s_per_lap: number;
  /** Which races the degradation was fitted on — never this one. */
  fitted_on: string[];
  fitted_on_count: number;
  held_out: boolean;
  /** Pirelli's nomination for this race, when known. */
  compounds?: Compounds | null;
  /** True when the session is still happening, so nothing was held out of the fit. */
  is_live?: boolean;
  caveats: string[];
  degradation_curve: DegradationCurve[];
  plans: Plan[];
  plans_with_risk: RiskyPlan[];
  plans_unavailable?: string;
  /** Set when the session is not a race, so nothing observed is comparable. */
  observed_unavailable?: string;
  stints: DriverStints[];
  /** For a race: each car's plans checked against the tyres it had. */
  tyre_sets?: { unavailable: string | null; cars: Record<string, CarPlanChecks> } | null;
}

async function post<T>(path: string): Promise<T> {
  const response = await fetch(path, { method: "POST" });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(detail.detail ?? `request failed: ${response.status}`);
  }
  return (await response.json()) as T;
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
  /** Slow the first time a season is asked for — the server fits it — then cached. */
  insight: (key: string, signal?: AbortSignal) =>
    get<Insight>(`/api/sessions/${key}/insight`, signal),
  liveStatus: (signal?: AbortSignal) => get<LiveStatus>("/api/live", signal),
  /** Slow the first time for a race and grid slot — a few thousand races — then cached. */
  places: (key: string, grid: number, signal?: AbortSignal) =>
    get<PlacesAnswer>(`/api/sessions/${key}/places?grid=${grid}`, signal),
  tyreSets: (key: string, signal?: AbortSignal) =>
    get<TyreSets>(`/api/sessions/${key}/tyre-sets`, signal),
  liveAttach: () => post<LiveStatus>("/api/live/attach"),
};

/** 92.608 -> "1:32.608", the way lap times are always written. */
export function formatLapTime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return "—";
  const minutes = Math.floor(seconds / 60);
  const rest = seconds - minutes * 60;
  return minutes > 0 ? `${minutes}:${rest.toFixed(3).padStart(6, "0")}` : rest.toFixed(3);
}

/** A sector time: shorter than a lap, so no minutes. */
export function formatSector(seconds: number | null | undefined): string {
  return seconds === null || seconds === undefined || !Number.isFinite(seconds) ? "—" : seconds.toFixed(3);
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
