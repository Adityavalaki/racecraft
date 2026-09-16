import { useEffect, useRef } from "react";
import type { Driver, SessionInfo } from "../api";

interface Props {
  info: SessionInfo;
  cars: Record<number, { x: number; y: number }>;
  drivers: Driver[];
  selected: number[];
}

/**
 * Cars on the circuit, drawn from GPS.
 *
 * The outline is the position trace of the session's fastest lap, so it is
 * the real racing line rather than a stylised shape. FastF1 gives a rotation
 * per circuit; applying it puts the map the way round broadcast shows it.
 */
export function TrackMap({ info, cars, drivers, selected }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const byNumber = new Map(drivers.map((d) => [d.driver_number, d]));

  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const context = element.getContext("2d");
    if (!context) return;

    const ratio = window.devicePixelRatio || 1;
    const width = element.clientWidth;
    const height = element.clientHeight;
    element.width = width * ratio;
    element.height = height * ratio;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);

    const rotation = Number(info.session.circuit_rotation_deg ?? 0);
    const points = info.outline.map(([x, y]) => rotate(x, y, rotation));
    const carPoints = Object.entries(cars).map(([number, point]) => ({
      number: Number(number),
      ...rotate(point.x, point.y, rotation),
    }));

    const all = points.concat(carPoints.map((c) => ({ x: c.x, y: c.y })));
    if (all.length === 0) {
      context.fillStyle = "#6b7887";
      context.font = "14px 'JetBrains Mono', monospace";
      context.fillText("no position data for this session", 16, height / 2);
      return;
    }

    const pad = 24;
    const xs = all.map((p) => p.x);
    const ys = all.map((p) => p.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const scale = Math.min((width - pad * 2) / (maxX - minX || 1), (height - pad * 2) / (maxY - minY || 1));
    const originX = (width - (maxX - minX) * scale) / 2 - minX * scale;
    // Screen y grows downward, so the track is flipped to read like a map.
    const originY = (height + (maxY - minY) * scale) / 2 + minY * scale;
    const project = (x: number, y: number) => [originX + x * scale, originY - y * scale] as const;

    if (points.length > 1) {
      context.beginPath();
      points.forEach((point, index) => {
        const [px, py] = project(point.x, point.y);
        index === 0 ? context.moveTo(px, py) : context.lineTo(px, py);
      });
      context.closePath();
      context.strokeStyle = "#2b333d";
      context.lineWidth = 10;
      context.lineJoin = "round";
      context.stroke();
      context.strokeStyle = "#39434f";
      context.lineWidth = 2;
      context.stroke();
    }

    for (const car of carPoints) {
      const [px, py] = project(car.x, car.y);
      const driver = byNumber.get(car.number);
      const isSelected = selected.includes(car.number);
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
        context.fillText(driver?.abbreviation ?? String(car.number), px + 11, py + 4);
      }
    }
  }, [info, cars, selected, drivers]);

  return <canvas className="track-map" ref={canvas} />;
}

function rotate(x: number, y: number, degrees: number): { x: number; y: number } {
  if (!degrees) return { x, y };
  const radians = (degrees * Math.PI) / 180;
  return {
    x: x * Math.cos(radians) - y * Math.sin(radians),
    y: x * Math.sin(radians) + y * Math.cos(radians),
  };
}
