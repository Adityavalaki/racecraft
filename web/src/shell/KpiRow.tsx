/** One headline figure: what it is, the figure, and a line on where it comes from. */
export interface Kpi {
  label: string;
  value: string;
  note?: string;
  /** "good" greens the figure, "bad" reds it; nothing leaves it plain. */
  tone?: "good" | "bad";
}

/**
 * The row of headline tiles under a screen's title: the few figures worth
 * reading before the table. Tiles with nothing to say (no value yet) are left
 * out rather than shown empty.
 */
export function KpiRow({ tiles }: { tiles: (Kpi | null | false | undefined)[] }) {
  const shown = tiles.filter((t): t is Kpi => Boolean(t && t.value));
  if (!shown.length) return null;
  return (
    <div className="kpi-row" role="list" aria-label="Headline figures">
      {shown.map((t) => (
        <div key={t.label} className="kpi" role="listitem">
          <span className="cap">{t.label}</span>
          <b className={`num${t.tone ? ` is-${t.tone}` : ""}`}>{t.value}</b>
          {t.note && <span className="kpi-note">{t.note}</span>}
        </div>
      ))}
    </div>
  );
}
