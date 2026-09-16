import { memo, useEffect, useRef } from "react";
import { useCanvasSize } from "../useCanvasSize";
import type { LapSeries } from "../api";

interface Props {
  series: LapSeries[];
  selected: number[];
  currentLap: number;
  onSelectLap: (lap: number) => void;
}

/**
 * The race trace: every driver's gap to the lap leader, lap by lap.
 *
 * This is the view where strategy becomes visible. A stop is a step down, the
 * climb back is the fresh-tyre advantage, and an undercut shows as one line
 * crossing another between stops. Selected drivers are drawn in team colour
 * over a muted field, so a pair can be compared without losing the context.
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

    const padding = { left: 46, right: 12, top: 12, bottom: 24 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const maxLap = Math.max(1, ...series.flatMap((s) => s.laps));
    const gaps = series.flatMap((s) => s.gap_to_leader_s.filter((g): g is number => g !== null));
    if (gaps.length === 0) return;
    // Clip the tail so one retirement or a lapped car does not flatten everyone.
    const maxGap = Math.max(10, percentile(gaps, 0.97));
    geometry.current = { left: padding.left, width: plotWidth, maxLap };

    const x = (lap: number) => padding.left + ((lap - 1) / Math.max(1, maxLap - 1)) * plotWidth;
    const y = (gap: number) => padding.top + Math.min(1, gap / maxGap) * plotHeight;

    context.strokeStyle = "#232a33";
    context.fillStyle = "#6b7887";
    context.font = "10px 'JetBrains Mono', monospace";
    context.lineWidth = 1;
    for (let gap = 0; gap <= maxGap; gap += gridStep(maxGap)) {
      const py = y(gap);
      context.beginPath();
      context.moveTo(padding.left, py);
      context.lineTo(width - padding.right, py);
      context.stroke();
      context.fillText(`${gap}s`, 8, py + 3);
    }

    const drawSeries = (item: LapSeries, emphasised: boolean) => {
      context.beginPath();
      let started = false;
      item.laps.forEach((lap, index) => {
        const gap = item.gap_to_leader_s[index];
        if (gap === null || gap === undefined) {
          started = false;
          return;
        }
        const px = x(lap);
        const py = y(gap);
        started ? context.lineTo(px, py) : context.moveTo(px, py);
        started = true;
      });
      context.strokeStyle = emphasised ? `#${item.team_color ?? "cccccc"}` : "#39434f";
      context.lineWidth = emphasised ? 2 : 1;
      context.globalAlpha = emphasised ? 1 : 0.55;
      context.stroke();
      context.globalAlpha = 1;

      if (emphasised) {
        item.pit_in.forEach((pitted, index) => {
          const gap = item.gap_to_leader_s[index];
          if (!pitted || gap === null || gap === undefined) return;
          context.beginPath();
          context.arc(x(item.laps[index]!), y(gap), 3, 0, Math.PI * 2);
          context.fillStyle = "#ff7a33";
          context.fill();
        });
      }
    };

    series.filter((s) => !selected.includes(s.driver_number)).forEach((s) => drawSeries(s, false));
    series.filter((s) => selected.includes(s.driver_number)).forEach((s) => drawSeries(s, true));

    const px = x(Math.max(1, currentLap));
    context.beginPath();
    context.moveTo(px, padding.top);
    context.lineTo(px, height - padding.bottom);
    context.strokeStyle = "#ff7a33";
    context.lineWidth = 1;
    context.stroke();

    context.fillStyle = "#6b7887";
    context.fillText("LAP 1", padding.left, height - 8);
    context.fillText(`LAP ${maxLap}`, width - padding.right - 46, height - 8);
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

function percentile(values: number[], fraction: number): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * fraction))] ?? 0;
}

function gridStep(maxGap: number): number {
  if (maxGap <= 20) return 5;
  if (maxGap <= 60) return 15;
  return Math.ceil(maxGap / 4 / 10) * 10;
}
