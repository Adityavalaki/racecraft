import { memo, useEffect, useMemo } from "react";
import type { Driver, LapTrace, SessionInfo } from "../api";
import { useCanvasSize } from "../useCanvasSize";

interface Props {
  info: SessionInfo;
  cars: Record<number, { x: number; y: number }>;
  drivers: Driver[];
  selected: number[];
  /** Label every car, not only the picked ones (L). */
  showNames?: boolean;
  /** Draw the DRS zones (D). There are none to draw for 2026. */
  showDrs?: boolean;
  /** 2026 on: cars eligible for overtake mode, ringed when `showDrs` is on (D). */
  overtakeEligible?: number[];
  /**
   * One car's last lap, to colour the circuit by: green where the throttle was
   * flat out, red where the brake was on. The pedal map.
   */
  pedalLap?: LapTrace | null;
  /** Where to draw the safety car while it is out; simulated by the server. */
  safetyCar?: { x: number; y: number } | null;
}

/**
 * Cars on the circuit, drawn from GPS.
 *
 * The outline is the median of the fastest laps' position traces, so it is
 * the real racing line at the real scale: measured against published circuit
 * lengths it comes out 1-2% short, which is what cutting the apexes costs.
 * FastF1's per-circuit rotation puts the map the way round broadcast shows
 * it, and one shared scale for both axes keeps the proportions honest.
 *
 * The track is projected once per size change and kept as a Path2D; only the
 * cars are redrawn as the clock advances.
 *
 * DRS zones are drawn over the track in the overtake colour where the flap
 * opened during the session (2023-2025: the 2026 cars have no DRS). From 2026
 * the same toggle rings the cars eligible for overtake mode instead.
 *
 * Given a lap, it is the pedal map: the circuit coloured by where that car had
 * the throttle flat and where it was on the brakes. The safety car is an
 * amber dot labelled SC, placed about 500 m ahead of the leader: F1 publishes
 * no position for it, so it is simulated, and the map says so.
 */
const NONE: number[] = [];
/** Throttle at or above this is flat out, for the pedal map. */
export const FLAT_OUT = 97;

export const TrackMap = memo(function TrackMap({
  info, cars, drivers, selected, showNames = false, showDrs = true, safetyCar = null, overtakeEligible = NONE,
  pedalLap = null,
}: Props) {
  const { ref, size } = useCanvasSize<HTMLCanvasElement>();
  const byNumber = useMemo(() => new Map(drivers.map((d) => [d.driver_number, d])), [drivers]);

  const projection = useMemo(() => {
    const rotation = Number(info.session.circuit_rotation_deg ?? 0);
    const points = info.outline.map(([x, y]) => rotate(x, y, rotation));
    if (points.length < 2 || size.width === 0 || size.height === 0) return null;

    const pad = 26;
    const xs = points.map((p) => p.x);
    const ys = points.map((p) => p.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    // One scale for both axes: the circuit keeps its true proportions.
    const scale = Math.min((size.width - pad * 2) / (maxX - minX || 1), (size.height - pad * 2) / (maxY - minY || 1));
    const originX = (size.width - (maxX - minX) * scale) / 2 - minX * scale;
    const originY = (size.height + (maxY - minY) * scale) / 2 + minY * scale;
    const project = (x: number, y: number) => {
      const r = rotate(x, y, rotation);
      return [originX + r.x * scale, originY - r.y * scale] as const;   // canvas y grows downward
    };

    const screen = points.map((point) => [originX + point.x * scale, originY - point.y * scale] as const);
    const path = new Path2D();
    screen.forEach(([px, py], index) => (index === 0 ? path.moveTo(px, py) : path.lineTo(px, py)));
    path.closePath();

    // Each zone is the stretch of outline between its two indices, running
    // forward and wrapping past the start line when the first is the larger.
    const loop = Math.max(1, screen.length - 1);                // the closing point repeats the first
    const drs = new Path2D();
    for (const [first, last] of info.drs_zones ?? []) {
      const count = ((last - first + loop) % loop) + 1;
      for (let k = 0; k < count; k += 1) {
        const [px, py] = screen[(first + k) % loop]!;
        k === 0 ? drs.moveTo(px, py) : drs.lineTo(px, py);
      }
    }
    return { project, path, drs, hasDrs: (info.drs_zones ?? []).length > 0 };
  }, [info, size.width, size.height]);

  // The pedal map: runs of flat-out throttle and of braking along the lap, as paths.
  const pedals = useMemo(() => {
    if (!projection || !pedalLap) return null;
    const runs = (on: (i: number) => boolean) => {
      const path = new Path2D();
      let open = false;
      for (let i = 0; i < pedalLap.distance.length; i += 1) {
        const x = pedalLap.x[i];
        const y = pedalLap.y[i];
        if (!on(i) || x == null || y == null) {
          open = false;
          continue;
        }
        const [px, py] = projection.project(x, y);
        if (open) path.lineTo(px, py);
        else path.moveTo(px, py);
        open = true;
      }
      return path;
    };
    return {
      throttle: runs((i) => (pedalLap.throttle[i] ?? 0) >= FLAT_OUT),
      brake: runs((i) => Boolean(pedalLap.brake[i])),
    };
  }, [projection, pedalLap]);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || size.width === 0) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.round(size.width * ratio);
    canvas.height = Math.round(size.height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, size.width, size.height);

    if (!projection) {
      context.fillStyle = "#8B8B96";
      context.font = "13px 'JetBrains Mono', monospace";
      context.fillText("no position data for this session", 16, size.height / 2);
      return;
    }

    context.lineJoin = "round";
    context.lineCap = "round";
    context.strokeStyle = "#1E1E24";
    context.lineWidth = 18;
    context.stroke(projection.path);
    context.strokeStyle = "#62626E";
    context.lineWidth = 2;
    context.stroke(projection.path);
    if (pedals) {
      context.strokeStyle = "#1FD17B";
      context.lineWidth = 5;
      context.stroke(pedals.throttle);
      context.strokeStyle = "#FF3B30";
      context.lineWidth = 8;
      context.stroke(pedals.brake);
    }
    if (showDrs && projection.hasDrs) {
      context.strokeStyle = "rgba(0, 194, 255, 0.85)";
      context.lineWidth = 3;
      context.stroke(projection.drs);
    }

    for (const [number, point] of Object.entries(cars)) {
      const [px, py] = projection.project(point.x, point.y);
      const driver = byNumber.get(Number(number));
      const isSelected = selected.includes(Number(number));
      if (showDrs && overtakeEligible.includes(Number(number))) {
        // A cyan halo: within a second of the car ahead, overtake mode on.
        context.beginPath();
        context.arc(px, py, isSelected ? 12 : 9.5, 0, Math.PI * 2);
        context.lineWidth = 2.5;
        context.strokeStyle = "rgba(0, 194, 255, 0.95)";
        context.stroke();
      }
      context.beginPath();
      context.arc(px, py, isSelected ? 8 : 5.5, 0, Math.PI * 2);
      context.fillStyle = `#${driver?.team_color ?? "999999"}`;
      context.fill();
      context.lineWidth = isSelected ? 2 : 1.5;
      context.strokeStyle = isSelected ? "#F4F4F6" : "#0A0A0C";
      context.stroke();
      const code = driver?.abbreviation ?? number;
      if (isSelected) {
        // A followed car is named on a white tag, in the display face.
        context.font = "italic 800 15px 'Barlow Condensed', 'Arial Narrow', sans-serif";
        const width = context.measureText(code).width + 14;
        const left = px + 12;
        context.fillStyle = "#F4F4F6";
        context.beginPath();
        context.roundRect?.(left, py - 10, width, 20, 5);
        if (!context.roundRect) context.rect(left, py - 10, width, 20);
        context.fill();
        context.fillStyle = "#0A0A0C";
        context.fillText(code, left + 7, py + 5);
      } else if (showNames) {
        context.fillStyle = "#C4C4CC";
        context.font = "italic 700 12px 'Barlow Condensed', 'Arial Narrow', sans-serif";
        context.fillText(code, px + 8, py + 4);
      }
    }

    if (safetyCar) {
      const [px, py] = projection.project(safetyCar.x, safetyCar.y);
      context.beginPath();
      context.arc(px, py, 8, 0, Math.PI * 2);
      context.fillStyle = "#FFA23A";
      context.fill();
      context.lineWidth = 2;
      context.strokeStyle = "#0A0A0C";
      context.stroke();
      context.fillStyle = "#10151a";
      context.font = "700 9px 'JetBrains Mono', monospace";
      context.fillText("SC", px - 6, py + 3);
      context.fillStyle = "#8B8B96";
      context.font = "10px 'JetBrains Mono', monospace";
      context.fillText("SC position simulated: F1 publishes none", 12, 18);
    }
  }, [ref, projection, cars, selected, byNumber, size.width, size.height, showNames, showDrs, safetyCar,
      overtakeEligible, pedals]);

  return <canvas className="track-map" ref={ref} />;
});

function rotate(x: number, y: number, degrees: number): { x: number; y: number } {
  if (!degrees) return { x, y };
  const radians = (degrees * Math.PI) / 180;
  return {
    x: x * Math.cos(radians) - y * Math.sin(radians),
    y: x * Math.sin(radians) + y * Math.cos(radians),
  };
}
