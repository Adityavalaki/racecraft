import { memo, useEffect, useRef } from "react";
import { useCanvasSize } from "../useCanvasSize";
import type { LapSeries } from "../api";

interface Props {
  series: LapSeries[];
  selected: number[];
  currentLap: number;
  onSelectLap: (lap: number) => void;
}

const PADDING = { left: 30, right: 34, top: 12, bottom: 22 };

/**
 * The race as positions, lap by lap.
 *
 * This was a gap chart — every driver's distance behind the leader in seconds
 * — which is the more precise view and the harder one to read. Twenty lines of
 * gap tell you how far apart cars are and almost nothing about what happened,
 * because the shape that matters is buried in a band of similar curves near
 * the top.
 *
 * Positions instead. A pit stop is a drop and a climb back, an overtake is one
 * line crossing another, and a strategy that worked is a line that ends higher
 * than it started. All twenty stay legible because there are only as many
 * levels as there are cars, and each is a step rather than a slope.
 *
 * What it gives up is distance: half a second and thirty seconds both show as
 * one place. The gap is still on the tower, where a number belongs.
 *
 * It draws only as far as the clock has reached, so the lines grow across the
 * panel while the race runs and retreat when you scrub back. The axis stays
 * fixed to the full distance rather than rescaling to what has been drawn:
 * a chart whose axis moves under a line makes the line look like it is doing
 * something it is not, and how much race is left is half of what a strategy
 * call turns on.
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
    // P1 at the top, and each place gets the middle of its own band so a line
    // never sits on a gridline.
    const y = (place: number) => PADDING.top + ((place - 0.5) / lastPlace) * plotHeight;

    context.font = "10px 'JetBrains Mono', monospace";
    context.textBaseline = "middle";

    // A faint line per place. Every tenth of the panel's height is a position,
    // so the levels themselves carry the scale and only a few need labelling.
    context.strokeStyle = "#1b222a";
    context.lineWidth = 1;
    for (let place = 1; place <= lastPlace; place += 1) {
      const py = y(place);
      context.beginPath();
      context.moveTo(PADDING.left, py);
      context.lineTo(width - PADDING.right, py);
      context.stroke();
      if (place === 1 || place % 5 === 0 || place === lastPlace) {
        context.fillStyle = "#6b7887";
        context.textAlign = "right";
        context.fillText(`P${place}`, PADDING.left - 6, py);
      }
    }

    const drawSeries = (item: LapSeries, emphasised: boolean) => {
      // Stepped: a car holds a place for a whole lap and then changes it, so a
      // sloped line would draw an overtake that happened gradually.
      context.beginPath();
      let previous: number | null = null;
      let head: { px: number; py: number } | null = null;
      item.laps.forEach((lap, index) => {
        if (lap > shownLap) return;                 // not run yet at this point in the race
        const place = item.position[index];
        if (place === null || place === undefined) {
          previous = null;
          return;
        }
        const px = x(lap);
        const py = y(place);
        if (previous === null) {
          context.moveTo(px, py);
        } else {
          context.lineTo(px, previous);
          context.lineTo(px, py);
        }
        previous = py;
        head = { px, py };
      });
      context.strokeStyle = emphasised ? `#${item.team_color ?? "cccccc"}` : "#39434f";
      context.lineWidth = emphasised ? 2.25 : 1;
      context.globalAlpha = emphasised ? 1 : 0.5;
      context.stroke();
      context.globalAlpha = 1;

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
      }

      // The driver's code rides the head of their own line, so the order reads
      // off the right-hand edge at whatever point the race has reached.
      const tip = head as { px: number; py: number } | null;
      if (tip) {
        const colour = emphasised ? `#${item.team_color ?? "cccccc"}` : "#6b7887";
        if (emphasised) {
          context.beginPath();
          context.arc(tip.px, tip.py, 2.5, 0, Math.PI * 2);
          context.fillStyle = colour;
          context.fill();
        }
        context.fillStyle = colour;
        context.textAlign = "left";
        context.fillText(item.abbreviation ?? String(item.driver_number), tip.px + 5, tip.py);
      }
    };

    series.filter((s) => !selected.includes(s.driver_number)).forEach((s) => drawSeries(s, false));
    series.filter((s) => selected.includes(s.driver_number)).forEach((s) => drawSeries(s, true));

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

    context.fillStyle = "#6b7887";
    context.textAlign = "left";
    context.fillText("LAP 1", PADDING.left, height - 8);
    context.fillStyle = "#ff7a33";
    context.textAlign = "center";
    context.fillText(`LAP ${shownLap}`, Math.min(width - PADDING.right - 24, Math.max(PADDING.left + 24, px)),
                     height - 8);
    context.fillStyle = "#6b7887";
    context.textAlign = "right";
    context.fillText(`${maxLap}`, width - PADDING.right, height - 8);
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
