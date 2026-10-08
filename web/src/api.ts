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
  /** Every change of track status in the session: 1 clear, 2 yellow, 4 SC, 5 red, 6 VSC, 7 VSC ending. */
  track_status?: { t: number; status: string; message: string }[];
  /**
   * Where DRS opens, as [first, last] indices into `outline` (first > last
   * wraps past the start line). Empty for 2026 (no DRS) and for live.
   */
  drs_zones?: [number, number][];
  /** 2026 on: race control switches overtake mode, the successor to DRS. */
  has_overtake?: boolean;
}

/** The three kinds of race control message. */
export type Topic = "stewards" | "track" | "noise";

/** How far along one thing the stewards are looking at has got. */
export interface Incident {
  stage: "noted" | "investigating" | "cleared" | "penalised";
  reason: string | null;
  cars: number[];
  opened_t: number;
  updated_t: number;
}

/** One race control message, read rather than raw. */
export interface RaceControlEvent {
  t: number;
  lap: number | null;
  kind: string;
  seconds: number | null;
  reason: string | null;
  cars: number[];
  incident: string | null;
  /** True when the message carries a verdict, which is what makes it the stewards'. */
  stewards: boolean;
  /** Which list it belongs in. See `api/penalties.Event.topic`. */
  topic: Topic;
  message: string;
  category?: string | null;
  flag?: string | null;
  scope?: string | null;
}

/**
 * What race control has said about one car, as of the clock's current time.
 *
 * `pending_s` is time the car still has to serve and `served_s` time it has;
 * `awarded_s` is the two together. Everything here is recomputed at each `t`,
 * so scrubbing back shows what was known then.
 */
export interface DriverPenalties {
  driver_number: number;
  pending_s: number;
  served_s: number;
  awarded_s: number;
  stop_go: number;
  drive_through: number;
  penalties: number;
  laps_deleted: number;
  black_and_white: number;
  reprimands: number;
  warnings: number;
  disqualified: boolean;
  under_investigation: number;
  noted: number;
  cleared: number;
  outstanding: boolean;
  incidents: Incident[];
  events: RaceControlEvent[];
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
  /** null when race control has said nothing about this car yet. */
  penalties: DriverPenalties | null;
  /**
   * Overtake mode (2026 on), estimated from the timing interval: null for a
   * session without it.
   */
  overtake?: "eligible" | "not_eligible" | "disabled" | null;
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
  weather: {
    air_temp: number | null;
    track_temp: number | null;
    rainfall: boolean | null;
    wind_speed?: number | null;
  } | null;
  /**
   * Where to draw the safety car while it is out: simulated, about 500 m ahead
   * of the leader, because F1 publishes no position for it.
   */
  safety_car?: { x: number; y: number; simulated: true } | null;
  /** Whether race control has overtake mode on; null for a session without it. */
  overtake?: { enabled: boolean } | null;
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
  /** Laps already on the set each stint starts on; all zeros on new tyres. */
  start_ages: number[];
  on_used_sets: boolean;
  expected_s?: number;
  green_s?: number;
}

/** What one car had in the garage when the race started. */
export interface TyreStock {
  driver: string;
  driver_number: number;
  grid: number | null;
  left: Record<string, { new: number; used: number[] }>;
  sets: number;
  notes: string[];
}

export interface PlacesAnswer {
  session_key: string;
  grid: number;
  runs: number;
  /** "car" when the sets that car actually had were raced, "new" for fresh ones. */
  tyres: "car" | "new";
  stock: TyreStock | null;
  /** Who started in each grid slot, when the race is in the lake. */
  grid_drivers: Record<string, string>;
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
    stock: Record<string, { new: number; used: number[] }> | null;
    /** Plans the car had no sets for, and why. */
    dropped: { plan: string; reason: string }[];
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

/** One session a sync looked at. */
export interface SyncItem {
  key: string;
  season: number;
  round: number;
  ident: string;
  event: string;
  name: string;
  /** pending, ingesting, written, present (already in the lake), failed */
  state: string;
  detail: string;
}

/** Bringing the latest race weekends into the lake, from the interface. */
export interface SyncStatus {
  state: "idle" | "planning" | "running" | "done" | "failed";
  weekends: string[];
  items: SyncItem[];
  counts: Record<string, number>;
  /** Sessions that were not in the lake when the sync looked. */
  to_fetch: number;
  /** The session being ingested now, if any. */
  current: string | null;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
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

/**
 * A request the server answered with an error. `status` lets a caller tell
 * "not ready yet" (409, live waiting for data) from something actually wrong.
 */
export class HttpError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "HttpError";
    this.status = status;
  }
}

/** One driver in a race prediction: chances, expected finish, and the readings behind them. */
export interface PredictionDriver {
  driver_number: number;
  abbreviation: string;
  team_name: string | null;
  team_color: string | null;
  grid: number;
  win: number;
  podium: number;
  points: number;
  dnf: number;
  expected: number;
  /** The likely range if the car finishes (10th to 90th percentile). */
  p10: number;
  /** The median finish, if the car finishes. */
  p50: number;
  p90: number;
  pace_s: number;
  pace_sd: number;
  signals: Record<string, number | null>;
}

export interface PredictionScore {
  rho: number;
  winner_hit: boolean;
  podium_hits: number;
  brier_win: number;
  brier_podium: number;
  logloss_win: number;
}

/** The weekend's race, predicted from before it started; with the result once there is one. */
export interface Prediction {
  race_key: string;
  event_name: string;
  year: number;
  round: number;
  drivers: PredictionDriver[];
  basis: {
    sessions: string[];
    form_races: string[];
    grid_source: string;
    retire_rate: number;
    runs: number;
    reference_plan: string;
    calibration: { fitted_on: string[] };
    notes: string[];
  };
  made_at: string;
  saved_at?: string;
  /** Saved before the race started, rather than rebuilt from pre-race data afterwards. */
  before_race: boolean;
  /** The race's season was one the signals were weighed on. */
  in_sample: boolean;
  result: { finish: Record<string, number>; scores: { model: PredictionScore; grid: PredictionScore } } | null;
}

/** One lap of one car by distance, every five metres: the pedal map and the traces. */
export interface LapTrace {
  driver_number: number;
  abbreviation: string | null;
  lap: number;
  lap_time_s: number | null;
  compound: string | null;
  tyre_life: number | null;
  start_t: number;
  length_m: number;
  step_m: number;
  distance: number[];
  /** Seconds since the lap started. */
  t: number[];
  speed: number[];
  throttle: number[];
  /** On or off: the public feed never says how hard. */
  brake: boolean[];
  gear: number[];
  x: (number | null)[];
  y: (number | null)[];
  brake_zones: { start_m: number; end_m: number; duration_s: number; entry_speed: number; min_speed: number }[];
  corners: { number: number; letter: string | null; distance: number }[];
  summary: { top_speed: number; min_speed: number; full_throttle_share: number; braking_share: number; brake_zones: number };
}

/** The last half-minute of one car, by time: t runs from -seconds to 0. */
export interface RecentTrace {
  driver_number: number;
  seconds: number;
  t: number[];
  speed: (number | null)[];
  throttle: (number | null)[];
  brake: (boolean | null)[];
  gear: (number | null)[];
}

export interface LapComparison {
  subject: LapTrace;
  reference: LapTrace;
  /** Positive where the subject is behind. */
  delta: { distance: number[]; delta_s: number[]; final_s: number | null };
}

/** When each car is best off stopping, and who can jump whom, at a moment in a race. */
export interface PitWindows {
  session_key: string;
  t: number;
  lap: number;
  total_laps: number;
  model: { degradation: Record<string, number>; compound_offset_s: Record<string, number>; pit_loss_s: number;
           pit_spread_s: number; fitted_on_count: number | null; held_out: boolean | null };
  cars: {
    driver_number: number;
    abbreviation: string | null;
    team_color: string | null;
    position: number | null;
    status: string;
    compound: string | null;
    age: number | null;
    laps_completed: number;
    stops: number | null;
    used: string[];
    window: { laps_until: number; window: [number, number]; most_likely_lap: number; next_compound: string; no_stop: boolean } | null;
  }[];
  undercuts: { chaser: number; target: number; gap_s: number; gain_s: number; chance: number; fresh_compound: string }[];
  notes: string[];
}

async function failure(response: Response): Promise<HttpError> {
  const detail = await response.json().catch(() => ({ detail: response.statusText }));
  return new HttpError(detail.detail ?? `request failed: ${response.status}`, response.status);
}

async function post<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { method: "POST", signal });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as T;
}

async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, { signal });
  if (!response.ok) throw await failure(response);
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
  /**
   * Race control up to `t`, newest first. Follows the clock like everything else.
   *
   * `topic` picks one of "stewards" (verdicts), "track" (safety car, flags, pit
   * exit, DRS, conditions) or "noise" (blue and sector flags); omit it for all
   * three. Filtering server-side matters — the limit is applied after it, so
   * asking for the stewards' last twenty gets twenty of theirs.
   */
  messages: (key: string, t: number, limit = 40, topic?: Topic, signal?: AbortSignal) =>
    get<RaceControlEvent[]>(
      `/api/sessions/${key}/messages?until=${t.toFixed(2)}&limit=${limit}` +
        (topic === undefined ? "" : `&topic=${topic}`),
      signal,
    ),
  liveStatus: (signal?: AbortSignal) => get<LiveStatus>("/api/live", signal),
  /** Slow the first time for a race and grid slot — a few thousand races — then cached. */
  places: (key: string, grid: number, tyres: "car" | "new" = "car", signal?: AbortSignal) =>
    get<PlacesAnswer>(`/api/sessions/${key}/places?grid=${grid}&tyres=${tyres}`, signal),
  tyreSets: (key: string, signal?: AbortSignal) =>
    get<TyreSets>(`/api/sessions/${key}/tyre-sets`, signal),
  /** Slow the first time for a season (the model is fitted), then quick. */
  pitWindows: (key: string, t: number, signal?: AbortSignal) =>
    get<PitWindows>(`/api/sessions/${key}/pit-windows?t=${t.toFixed(2)}`, signal),
  /** One lap by distance: `lap`, or the latest finished by `t`. */
  lap: (key: string, driver: number, opts: { lap?: number; t?: number }, signal?: AbortSignal) =>
    get<LapTrace>(`/api/sessions/${key}/lap?driver=${driver}`
      + (opts.lap != null ? `&lap=${opts.lap}` : "") + (opts.t != null ? `&t=${opts.t.toFixed(2)}` : ""), signal),
  recent: (key: string, driver: number, t: number, seconds = 30, signal?: AbortSignal) =>
    get<RecentTrace>(`/api/sessions/${key}/recent?driver=${driver}&t=${t.toFixed(2)}&seconds=${seconds}`, signal),
  compare: (key: string, driver: number, ref: number, opts: { lap?: number; refLap?: number; t?: number },
            signal?: AbortSignal) =>
    get<LapComparison>(`/api/sessions/${key}/compare?driver=${driver}&ref=${ref}`
      + (opts.lap != null ? `&lap=${opts.lap}` : "") + (opts.refLap != null ? `&ref_lap=${opts.refLap}` : "")
      + (opts.t != null ? `&t=${opts.t.toFixed(2)}` : ""), signal),
  /** Twenty seconds the first time for a weekend, then saved for good. */
  prediction: (key: string, signal?: AbortSignal) =>
    get<Prediction>(`/api/sessions/${key}/prediction`, signal),
  /** Points live at the newest recording. Attaching again to the same one changes nothing. */
  liveAttach: (signal?: AbortSignal) => post<LiveStatus>("/api/live/attach", signal),
  /** Starts a sync of the latest race weekends, or reports the one running. */
  sync: () => post<SyncStatus>("/api/sync"),
  syncStatus: (signal?: AbortSignal) => get<SyncStatus>("/api/sync", signal),
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
  SOFT: "#FF3B30",
  MEDIUM: "#FFD60A",
  HARD: "#F2F2F2",
  INTERMEDIATE: "#3DD68C",
  WET: "#3E8EF7",
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
