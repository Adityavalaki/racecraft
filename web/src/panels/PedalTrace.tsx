import { memo } from "react";
import type { RecentTrace } from "../api";

/** Speed is drawn between these, in km/h: a slow hairpin to a fast straight. */
export const SPEED_FLOOR = 40;
export const SPEED_CEILING = 350;

/**
 * Segments of a series with the gaps (null) left out, as SVG path data.
 * `y` turns a value into a height; `x` an index into a position.
 */
export function linePath(values: (number | null)[], x: (i: number) => number, y: (v: number) => number): string {
  let d = "";
  let open = false;
  values.forEach((value, i) => {
    if (value == null) {
      open = false;
      return;
    }
    d += `${open ? "L" : "M"}${x(i).toFixed(1)} ${y(value).toFixed(1)}`;
    open = true;
  });
  return d;
}

/** Runs of true, as [first index, last index]. */
export function runs(values: (boolean | null)[]): [number, number][] {
  const out: [number, number][] = [];
  let start = -1;
  values.forEach((on, i) => {
    if (on && start < 0) start = i;
    if (!on && start >= 0) {
      out.push([start, i - 1]);
      start = -1;
    }
  });
  if (start >= 0) out.push([start, values.length - 1]);
  return out;
}

/**
 * The last half-minute of one car: speed as a purple line across the top,
 * throttle as a green area below it, and the brake as red blocks along the
 * foot, square because the feed only says on or off. Now is the right edge.
 */
export const PedalTrace = memo(function PedalTrace({ trace, code }: { trace: RecentTrace | null; code: string }) {
  if (!trace || trace.t.length < 2) {
    return <div className="pedal-trace is-empty">{trace ? "No car data here." : "Loading telemetry…"}</div>;
  }
  const n = trace.t.length;
  // By time, not by sample: the window slides every frame, so the trace scrolls rather than steps.
  const x = (i: number) => ((trace.t[i]! + trace.seconds) / trace.seconds) * 600;
  const speedY = (v: number) => 46 - ((Math.min(Math.max(v, SPEED_FLOOR), SPEED_CEILING) - SPEED_FLOOR) / (SPEED_CEILING - SPEED_FLOOR)) * 42;
  const throttleY = (v: number) => 82 - (Math.min(Math.max(v, 0), 100) / 100) * 30;
  const speed = linePath(trace.speed, x, speedY);
  const throttle = linePath(trace.throttle, x, throttleY);
  // The area closes down to the floor under each unbroken stretch of throttle.
  const area = throttle.split("M").filter(Boolean).map((seg) => {
    const points = seg.split("L");
    const first = points[0]!.split(" ")[0];
    const last = points[points.length - 1]!.split(" ")[0];
    return `M${seg}L${last} 82L${first} 82Z`;
  }).join("");
  const brakes = runs(trace.brake).map(([a, b]) => `M${x(a).toFixed(1)} 88H${x(Math.min(b + 1, n - 1)).toFixed(1)}V98H${x(a).toFixed(1)}Z`).join("");
  return (
    <div className="pedal-trace">
      <svg viewBox="0 0 600 100" preserveAspectRatio="none" role="img"
           aria-label={`Last ${Math.round(trace.seconds)} seconds of speed, throttle and brake for ${code}`}>
        <path d="M0 50H600M0 87H600" stroke="#26262C" strokeWidth="1" vectorEffect="non-scaling-stroke" fill="none" />
        <path d={area} fill="rgba(31, 209, 123, 0.28)" />
        <path d={throttle} fill="none" stroke="var(--throttle)" strokeWidth="1.6" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        <path d={speed} fill="none" stroke="var(--speed)" strokeWidth="2" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
        <path d={brakes} fill="var(--brake)" />
      </svg>
      <span className="trace-label is-speed">Speed</span>
      <span className="trace-label is-throttle">Throttle</span>
      <span className="trace-label is-brake">Brake</span>
      <span className="trace-span">last {Math.round(trace.seconds)} s</span>
    </div>
  );
});
