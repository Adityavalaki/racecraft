import { memo, useEffect, useMemo } from "react";
import type { Driver, SessionInfo } from "../api";
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
 * DRS zones are drawn over the track in green where the flap opened during
 * the session (2023-2025: the 2026 cars have no DRS). The safety car is an
 * amber dot labelled SC, placed about 500 m ahead of the leader: F1 publishes
 * no position for it, so it is simulated, and the map says so.
 */
export const TrackMap = memo(function TrackMap({
  info, cars, drivers, selected, showNames = false, showDrs = true, safetyCar = null,
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
      context.fillStyle = "#6b7887";
      context.font = "13px 'JetBrains Mono', monospace";
      context.fillText("no position data for this session", 16, size.height / 2);
      return;
    }

    context.lineJoin = "round";
    context.lineCap = "round";
    context.strokeStyle = "#2b333d";
    context.lineWidth = 11;
    context.stroke(projection.path);
    context.strokeStyle = "#394450";
    context.lineWidth = 2;
    context.stroke(projection.path);
    if (showDrs && projection.hasDrs) {
      context.strokeStyle = "rgba(69, 199, 127, 0.85)";
      context.lineWidth = 4;
      context.stroke(projection.drs);
    }

    for (const [number, point] of Object.entries(cars)) {
      const [px, py] = projection.project(point.x, point.y);
      const driver = byNumber.get(Number(number));
      const isSelected = selected.includes(Number(number));
      context.beginPath();
      context.arc(px, py, isSelected ? 8 : 5.5, 0, Math.PI * 2);
      context.fillStyle = `#${driver?.team_color ?? "999999"}`;
      context.fill();
      if (isSelected) {
        context.lineWidth = 2;
        context.strokeStyle = "#ffffff";
        context.stroke();
      }
      if (isSelected || showNames) {
        context.fillStyle = isSelected ? "#ffffff" : "#a8b4c1";
        context.font = isSelected ? "600 12px 'Saira Condensed', sans-serif" : "500 10px 'Saira Condensed', sans-serif";
        context.fillText(driver?.abbreviation ?? number, px + (isSelected ? 11 : 8), py + 4);
      }
    }

    if (safetyCar) {
      const [px, py] = projection.project(safetyCar.x, safetyCar.y);
      context.beginPath();
      context.arc(px, py, 8, 0, Math.PI * 2);
      context.fillStyle = "#f2c53d";
      context.fill();
      context.lineWidth = 2;
      context.strokeStyle = "#ff7a33";
      context.stroke();
      context.fillStyle = "#10151a";
      context.font = "700 9px 'JetBrains Mono', monospace";
      context.fillText("SC", px - 6, py + 3);
      context.fillStyle = "#6b7887";
      context.font = "10px 'JetBrains Mono', monospace";
      context.fillText("SC position simulated: F1 publishes none", 12, size.height - 10);
    }
  }, [ref, projection, cars, selected, byNumber, size.width, size.height, showNames, showDrs, safetyCar]);

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
