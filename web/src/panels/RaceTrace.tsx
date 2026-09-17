import { memo, useEffect, useRef } from "react";
import { useCanvasSize } from "../useCanvasSize";
import type { LapSeries } from "../api";

interface Props {
  series: LapSeries[];
  selected: number[];
  currentLap: number;
  onSelectLap: (lap: number) => void;
}

const PADDING = { left: 28, right: 46, top: 10, bottom: 22 };
const LAP_GRID = 10;

/**
 * Race progression: every driver's position, lap by lap.
 *
 * This follows the standard convention — position down the left, lap across
 * the bottom, one line per car in its team colour, driver codes down the
 * right-hand edge — because it is a chart people already know how to read, and
 * being legible beats being novel.
 *
 * What it shows that a gap chart does not: a pit stop is a dive and a climb
 * back, an overtake is one line crossing another, a safety car is the whole
 * field converging at once, and a retirement is a line that stops. The cost is
 * distance — half a second and thirty seconds are both one place — and the gap
 * is on the timing tower, where a number belongs.
 *
 * Transitions are ramps rather than right-angle steps. A place does change at
 * one crossing of the line, so the step is the truer shape, but with twenty
 * cars the steps stack into a grid of verticals that hides which line went
 * where. The ramp keeps each line followable, which is the entire job.
 *
 * It draws only as far as the clock has reached, so the lines grow across the
 * panel while the race runs and retreat when you scrub back. The axis stays
 * pinned to the full distance rather than rescaling to what has been drawn: an
 * axis that moves under a line makes the line look like it is doing something
 * it is not, and how much race is left is half of what a strategy call turns
 * on.
 */
export const RaceTrace = memo(function RaceTrace({ series, selected, currentLap, onSelectLap }: Props) {
  const { ref: canvas, size } = useCanvasSize<HTMLCanvasElement>();
  const geometry = useRef({ left: 0, width: 1, maxLap: 1 });

  useEffect(() => {
    const element = canvas.current;
    if (!element || size.width === 0) return;
    const context = element.getContext("2d");
    if (!context) return;

    const ratio = window.devicePixelRatio || 1;
    const { width, height } = size;
    element.width = Math.round(width * ratio);
    element.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);

    const plotWidth = width - PADDING.left - PADDING.right;
    const plotHeight = height - PADDING.top - PADDING.bottom;
    if (plotWidth < 40 || plotHeight < 30) return;

    const maxLap = Math.max(1, ...series.flatMap((s) => s.laps));
    const positions = series.flatMap((s) => s.position.filter((p): p is number => p !== null));
    if (positions.length === 0) return;
    const lastPlace = Math.max(...positions);
    // Clamped to at least one lap: at a standing start there is nothing to draw
    // yet, and an empty panel reads as broken rather than as "not started".
    const shownLap = Math.min(maxLap, Math.max(1, currentLap));
    geometry.current = { left: PADDING.left, width: plotWidth, maxLap };

    const x = (lap: number) => PADDING.left + ((lap - 1) / Math.max(1, maxLap - 1)) * plotWidth;
    const y = (place: number) => PADDING.top + ((place - 1) / Math.max(1, lastPlace - 1)) * plotHeight;

    context.font = "9px 'JetBrains Mono', monospace";
    context.textBaseline = "middle";
    const rowHeight = plotHeight / Math.max(1, lastPlace - 1);
    const labelEvery = rowHeight < 11 ? 2 : 1;      // skip every other number when tight

    context.strokeStyle = "#1b222a";
    context.lineWidth = 1;
    for (let place = 1; place <= lastPlace; place += 1) {
      const py = y(place);
      context.beginPath();
      context.moveTo(PADDING.left, py);
      context.lineTo(width - PADDING.right, py);
      context.stroke();
      if (place === 1 || place === lastPlace || place % labelEvery === 0) {
        context.fillStyle = "#6b7887";
        context.textAlign = "right";
        context.fillText(String(place), PADDING.left - 5, py);
      }
    }
    for (let lap = LAP_GRID; lap < maxLap; lap += LAP_GRID) {
      context.beginPath();
      context.moveTo(x(lap), PADDING.top);
      context.lineTo(x(lap), height - PADDING.bottom);
      context.stroke();
      context.fillStyle = "#6b7887";
      context.textAlign = "center";
      context.textBaseline = "top";
      context.fillText(String(lap), x(lap), height - PADDING.bottom + 6);
      context.textBaseline = "middle";
    }

    const anySelected = selected.length > 0;

    const drawSeries = (item: LapSeries, emphasised: boolean) => {
      context.beginPath();
      let started = false;
      let head: { px: number; py: number } | null = null;
      item.laps.forEach((lap, index) => {
        if (lap > shownLap) return;                 // not run yet at this point in the race
        const place = item.position[index];
        if (place === null || place === undefined) {
          started = false;
          return;
        }
        const px = x(lap);
        const py = y(place);
        started ? context.lineTo(px, py) : context.moveTo(px, py);
        started = true;
        head = { px, py };
      });

      const colour = `#${item.team_color ?? "8c98a5"}`;
      context.strokeStyle = colour;
      context.lineWidth = emphasised ? 2.5 : 1.4;
      // Every car keeps its own colour. Selecting some dims the rest rather
      // than draining them grey, so the field stays readable underneath.
      context.globalAlpha = emphasised ? 1 : anySelected ? 0.22 : 0.82;
      context.stroke();

      if (emphasised) {
        item.pit_in.forEach((pitted, index) => {
          const place = item.position[index];
          if (!pitted || place === null || place === undefined) return;
          if (item.laps[index]! > shownLap) return;
          context.beginPath();
          context.arc(x(item.laps[index]!), y(place), 3, 0, Math.PI * 2);
          context.fillStyle = "#ff7a33";
          context.fill();
        });
        const tip = head as { px: number; py: number } | null;
        if (tip) {
          context.beginPath();
          context.arc(tip.px, tip.py, 2.5, 0, Math.PI * 2);
          context.fillStyle = colour;
          context.fill();
        }
      }
      context.globalAlpha = 1;
    };

    series.filter((s) => !selected.includes(s.driver_number)).forEach((s) => drawSeries(s, false));
    series.filter((s) => selected.includes(s.driver_number)).forEach((s) => drawSeries(s, true));

    // Driver codes down the right-hand edge, each at the place its car holds
    // right now. Complete, that is the finishing order; mid-race it is the
    // running order, which makes the gutter a legend and a leaderboard at once.
    for (const item of series) {
      const place = placeAt(item, shownLap);
      if (place === null) continue;
      const emphasised = selected.includes(item.driver_number);
      context.fillStyle = `#${item.team_color ?? "8c98a5"}`;
      context.globalAlpha = emphasised ? 1 : anySelected ? 0.4 : 0.9;
      context.textAlign = "left";
      context.fillText(item.abbreviation ?? String(item.driver_number),
                       width - PADDING.right + 6, y(place));
      context.globalAlpha = 1;
    }

    // The leading edge: where the race has got to, and where the lines stop.
    const px = x(shownLap);
    context.beginPath();
    context.moveTo(px, PADDING.top);
    context.lineTo(px, height - PADDING.bottom);
    context.strokeStyle = "#ff7a33";
    context.globalAlpha = 0.5;
    context.lineWidth = 1;
    context.stroke();
    context.globalAlpha = 1;

    context.textBaseline = "top";
    context.fillStyle = "#6b7887";
    context.textAlign = "left";
    context.fillText("LAP", PADDING.left, height - PADDING.bottom + 6);
    context.fillStyle = "#ff7a33";
    context.textAlign = "center";
    context.fillText(`LAP ${shownLap}`,
                     Math.min(width - PADDING.right - 22, Math.max(PADDING.left + 26, px)),
                     height - PADDING.bottom + 6);
  }, [canvas, series, selected, currentLap, size.width, size.height]);

  return (
    <canvas
      className="race-trace"
      ref={canvas}
      onClick={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        const { left, width, maxLap } = geometry.current;
        const fraction = (event.clientX - rect.left - left) / width;
        onSelectLap(Math.round(1 + fraction * (maxLap - 1)));
      }}
    />
  );
});

/** Where a driver stood on `lap`, or on the last lap they completed before it. */
function placeAt(item: LapSeries, lap: number): number | null {
  let found: number | null = null;
  for (let index = 0; index < item.laps.length; index += 1) {
    if (item.laps[index]! > lap) break;
    const place = item.position[index];
    if (place !== null && place !== undefined) found = place;
  }
  return found;
}
