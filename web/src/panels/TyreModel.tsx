import { memo, useEffect, useState } from "react";
import { useCanvasSize } from "../useCanvasSize";
import { COMPOUND_COLORS, type Insight } from "../api";

interface Props {
  insight: Insight | null;
  loading: boolean;
  error: string | null;
}

const AXIS = { left: 44, right: 14, top: 14, bottom: 30 };

/**
 * Modelled tyre wear against what this race's tyres actually did.
 *
 * The line is a prediction, not a description: degradation is fitted on the
 * season's *other* races, so it was never shown the laps the dots come from.
 * The dots are this race's own partial residuals — lap time with driver, fuel
 * and track evolution removed — which is the same quantity the line measures.
 *
 * One compound at a time. All three at once meant six lines and three clouds of
 * dots overlapping in a panel a few hundred pixels tall, and the comparison
 * that matters — this compound's line against this compound's dots — was the
 * one the clutter hid. The rates sit side by side above the chart, so the
 * comparison between compounds is still a glance away.
 *
 * Two lines are drawn. The solid one is what the strategy model actually uses,
 * degradation multiplied by 1.5; the faint one is the raw measurement. The gap
 * between them is the cliff nobody records, and putting both on screen is the
 * only honest way to show a number that was adjusted.
 */
export const TyreModel = memo(function TyreModel({ insight, loading, error }: Props) {
  const { ref: canvas, size } = useCanvasSize<HTMLCanvasElement>();
  const [chosen, setChosen] = useState<string | null>(null);

  const available = (insight?.degradation_curve ?? []).filter((c) => c.points.length > 0);
  // Default to the softest compound present, which is the one whose wear
  // decides most stop calls.
  const order = ["SOFT", "MEDIUM", "HARD"];
  const ordered = [...available].sort((a, b) => order.indexOf(a.compound) - order.indexOf(b.compound));
  const active = ordered.find((c) => c.compound === chosen) ?? ordered[0] ?? null;

  useEffect(() => {
    const element = canvas.current;
    if (!element || size.width === 0 || !insight || !active) return;
    const context = element.getContext("2d");
    if (!context) return;

    const ratio = window.devicePixelRatio || 1;
    const { width, height } = size;
    element.width = Math.round(width * ratio);
    element.height = Math.round(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);

    const curves = [active];

    const plotWidth = width - AXIS.left - AXIS.right;
    const plotHeight = height - AXIS.top - AXIS.bottom;
    if (plotWidth < 40 || plotHeight < 40) return;

    const maxAge = Math.max(...curves.map((c) => c.points[c.points.length - 1]!.age));
    const values = curves.flatMap((c) =>
      c.points.flatMap((p) => [p.model_s, ...(p.observed_s === null ? [] : [p.observed_s])]),
    );
    const maxValue = Math.max(0.5, ...values);
    const minValue = Math.min(0, ...values);
    const span = maxValue - minValue || 1;

    const x = (age: number) => AXIS.left + ((age - 1) / Math.max(1, maxAge - 1)) * plotWidth;
    const y = (seconds: number) => AXIS.top + (1 - (seconds - minValue) / span) * plotHeight;

    // Grid and axis, drawn to the scale the marks use.
    context.font = "10px 'JetBrains Mono', monospace";
    context.textBaseline = "middle";
    const step = gridStep(span);
    for (let v = Math.ceil(minValue / step) * step; v <= maxValue + 1e-9; v += step) {
      const py = y(v);
      context.strokeStyle = Math.abs(v) < 1e-9 ? "#39434f" : "#232a33";
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(AXIS.left, py);
      context.lineTo(width - AXIS.right, py);
      context.stroke();
      context.fillStyle = "#6b7887";
      context.textAlign = "right";
      context.fillText(`${v > 0 ? "+" : ""}${v.toFixed(1)}s`, AXIS.left - 6, py);
    }

    context.textAlign = "center";
    context.textBaseline = "top";
    context.fillStyle = "#6b7887";
    for (const age of axisTicks(maxAge)) {
      context.fillText(String(age), x(age), height - AXIS.bottom + 8);
    }
    context.fillText("tyre age, laps", AXIS.left + plotWidth / 2, height - 12);

    for (const curve of curves) {
      const colour = COMPOUND_COLORS[curve.compound] ?? "#a8b4c1";

      // The raw measurement, before the 1.5 scaling.
      context.strokeStyle = colour;
      context.globalAlpha = 0.28;
      context.setLineDash([3, 3]);
      context.lineWidth = 1.25;
      context.beginPath();
      curve.points.forEach((p, i) =>
        i === 0 ? context.moveTo(x(p.age), y(p.model_unscaled_s)) : context.lineTo(x(p.age), y(p.model_unscaled_s)),
      );
      context.stroke();

      // The line the plans are actually costed on.
      context.setLineDash([]);
      context.globalAlpha = 1;
      context.lineWidth = 1.75;
      context.beginPath();
      curve.points.forEach((p, i) =>
        i === 0 ? context.moveTo(x(p.age), y(p.model_s)) : context.lineTo(x(p.age), y(p.model_s)),
      );
      context.stroke();

      // What happened. Marks are sized by how many laps stand behind them, so
      // a point resting on four laps cannot pass for one resting on twenty.
      context.fillStyle = colour;
      for (const point of curve.points) {
        if (point.observed_s === null) continue;
        const radius = 1.6 + Math.min(2.4, Math.sqrt(point.laps) / 2.2);
        context.globalAlpha = 0.75;
        context.beginPath();
        context.arc(x(point.age), y(point.observed_s), radius, 0, Math.PI * 2);
        context.fill();
      }
      context.globalAlpha = 1;
    }
  }, [canvas, size, insight, active]);

  if (loading) return <div className="panel-note">Fitting the season… this takes a few seconds the first time.</div>;
  if (error) return <div className="panel-note error">{error}</div>;
  if (!insight) return <div className="panel-note">No model for this session.</div>;

  if (!active) {
    return <div className="panel-note">No dry-tyre laps here to measure wear from.</div>;
  }

  return (
    <div className="tyre-model">
      <div className="tyre-legend" role="radiogroup" aria-label="Compound">
        {ordered.map((curve) => (
          <button
            key={curve.compound}
            type="button"
            role="radio"
            aria-checked={curve.compound === active.compound}
            className={`legend-item${curve.compound === active.compound ? " is-active" : ""}`}
            onClick={() => setChosen(curve.compound)}
          >
            <i className="swatch" style={{ background: COMPOUND_COLORS[curve.compound] ?? "#a8b4c1" }} />
            {curve.compound.toLowerCase()}
            {insight.compounds && (
              <em className="compound-code">{insight.compounds[curve.compound as "HARD" | "MEDIUM" | "SOFT"]}</em>
            )}
            <b>{(insight.degradation_used[curve.compound] ?? 0).toFixed(3)}</b>
            <small>s/lap</small>
          </button>
        ))}
      </div>
      <canvas ref={canvas} className="tyre-canvas" />
      <p className="tyre-note">
        Line: fitted on {insight.fitted_on_count} {insight.is_race ? "other " : ""}
        {insight.year} race{insight.fitted_on_count === 1 ? "" : "s"}
        {insight.is_race ? ", never this one" : ""}. Dashed is the raw measurement, solid the
        ×{insight.scale} used for plans — race data cannot see past the age teams accept, so the
        raw figure understates a long stint.{" "}
        {insight.is_race ? "Dots: what this race did." : insight.observed_unavailable}
      </p>
    </div>
  );
});

/** A round-ish step that yields roughly five gridlines across the span. */
function gridStep(span: number): number {
  const rough = span / 5;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const normalised = rough / magnitude;
  const nice = normalised <= 1 ? 1 : normalised <= 2 ? 2 : normalised <= 5 ? 5 : 10;
  return nice * magnitude;
}

function axisTicks(maxAge: number): number[] {
  const step = maxAge <= 12 ? 2 : maxAge <= 30 ? 5 : 10;
  const ticks: number[] = [];
  for (let age = 1; age <= maxAge; age += step) ticks.push(age);
  if (ticks[ticks.length - 1] !== maxAge) ticks.push(maxAge);
  return ticks;
}
