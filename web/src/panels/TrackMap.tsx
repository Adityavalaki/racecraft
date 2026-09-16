import { memo, useEffect, useMemo } from "react";
import type { Driver, SessionInfo } from "../api";
import { useCanvasSize } from "../useCanvasSize";

interface Props {
  info: SessionInfo;
  cars: Record<number, { x: number; y: number }>;
  drivers: Driver[];
  selected: number[];
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
 */
export const TrackMap = memo(function TrackMap({ info, cars, drivers, selected }: Props) {
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

    const path = new Path2D();
    points.forEach((point, index) => {
      const px = originX + point.x * scale;
      const py = originY - point.y * scale;
      index === 0 ? path.moveTo(px, py) : path.lineTo(px, py);
    });
    path.closePath();
    return { project, path };
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
        context.fillStyle = "#ffffff";
        context.font = "600 12px 'Saira Condensed', sans-serif";
        context.fillText(driver?.abbreviation ?? number, px + 11, py + 4);
      }
    }
  }, [ref, projection, cars, selected, byNumber, size.width, size.height]);

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
