import { useEffect, useState, type ReactNode } from "react";
import { api, type DataChoice } from "../api";
import { screenById } from "../features";
import { DATA_OPTIONS } from "../panels/DataChooser";
import { SyncButton } from "../panels/SyncButton";
import { ScreenHeader } from "../shell/ScreenHeader";
import { SHORTCUTS } from "../shortcuts";
import { speedIn, type Settings } from "../settings";

function Segmented<T extends string>({ label, value, options, onChange }: {
  label: string;
  value: T;
  options: [T, string][];
  onChange: (value: T) => void;
}) {
  return (
    <div className="segmented" role="radiogroup" aria-label={label}>
      {options.map(([key, text]) => (
        <button key={key} type="button" role="radio" aria-checked={value === key}
                className={value === key ? "is-on" : ""} onClick={() => onChange(key)}>
          {text}
        </button>
      ))}
    </div>
  );
}

function Switch({ label, on, onChange }: { label: string; on: boolean; onChange: (on: boolean) => void }) {
  return (
    <button type="button" role="switch" aria-checked={on} aria-label={label} className={`switch${on ? " is-on" : ""}`}
            onClick={() => onChange(!on)}>
      <span className="switch-knob" aria-hidden="true" />
    </button>
  );
}

function Row({ title, hint, children }: { title: string; hint: string; children: ReactNode }) {
  return (
    <div className="setting-row">
      <div className="setting-text"><span className="setting-title">{title}</span><span className="setting-hint">{hint}</span></div>
      {children}
    </div>
  );
}

/**
 * How Racecraft looks, and where its data comes from. Every change shows in
 * the preview straight away, and in every window, pop-outs included.
 */
export function SettingsScreen({ settings, update, picker, onSynced }: {
  settings: Settings;
  update: (change: Partial<Settings>) => void;
  picker?: ReactNode;
  onSynced: () => void;
}) {
  const screen = screenById("settings")!;
  const fast = speedIn(312, settings.units);
  const fast2 = speedIn(305, settings.units);
  // A server that cannot say simply shows no row.
  const [dataChoice, setDataChoice] = useState<DataChoice | null>(null);
  useEffect(() => {
    api.dataChoice().then((answer) => setDataChoice(answer.choice ?? null)).catch(() => undefined);
  }, []);
  const chooseData = async (next: DataChoice) => {
    try {
      await api.chooseData(next);
      setDataChoice(next);
    } catch {
      // Still showing the old choice, which is still the one in force.
    }
  };
  return (
    <div className="screen">
      <ScreenHeader title={screen.title} hint={screen.hint} picker={picker} />
      <main className="screen-body screen-columns settings">
        <div className="settings-col">
          <section className="panel" aria-label="Display">
            <div className="panel-bar"><h2>Display</h2><span className="panel-meta">Changes show in the preview straight away.</span></div>
            <Row title="Units" hint="Speed on every screen.">
              <Segmented label="Units" value={settings.units} options={[["metric", "Metric"], ["imperial", "Imperial"]]}
                         onChange={(units) => update({ units })} />
            </Row>
            <Row title="Density" hint="Row height in the timing tower and lists.">
              <Segmented label="Density" value={settings.density} options={[["comfortable", "Comfortable"], ["compact", "Compact"]]}
                         onChange={(density) => update({ density })} />
            </Row>
            <Row title="Header clock" hint="Beside the lap on the replay: the session clock, or the lap alone.">
              <Segmented label="Header clock" value={settings.clock} options={[["race", "Race clock"], ["lap", "Lap"]]}
                         onChange={(clock) => update({ clock })} />
            </Row>
          </section>
          <section className="panel" aria-label="Pedal map">
            <div className="panel-bar"><h2>Pedal map</h2><span className="panel-meta">What is drawn on the track.</span></div>
            <Row title="Driver codes on cars" hint="Shortcut: L">
              <Switch label="Driver codes on cars" on={settings.names} onChange={(names) => update({ names })} />
            </Row>
            <Row title="Overtake rings and DRS zones" hint="Shortcut: D. Rings from 2026, DRS zones before.">
              <Switch label="Overtake rings and DRS zones" on={settings.rings} onChange={(rings) => update({ rings })} />
            </Row>
          </section>
          <section className="panel" aria-label="Data">
            <div className="panel-bar"><h2>Data</h2><span className="panel-meta">Race data from FastF1, OpenF1, Jolpica and TracingInsights.</span></div>
            {dataChoice && (
              <Row title="What to download"
                   hint={`${DATA_OPTIONS.find((o) => o.id === dataChoice)?.cost}. Sessions already here stay. A change begins when any download in progress ends, or next time Racecraft opens.`}>
                <Segmented label="What to download" value={dataChoice} options={DATA_OPTIONS.map((o) => [o.id, o.label])}
                           onChange={(next) => void chooseData(next)} />
              </Row>
            )}
            <Row title="Refresh" hint="Fetches anything from your choice that is not on this device yet. It also runs by itself while Racecraft is open.">
              {/* A new key on each choice, so it shows the download at once rather than at its next idle look. */}
              <SyncButton key={dataChoice ?? ""} onSynced={onSynced} />
            </Row>
            <Row title="Sources" hint="Since October 2026 F1's archive needs an F1 TV login, so new sessions are built from free sources. Each session names its own beside the session picker.">
              <span className="settings-credits">
                FastF1 (MIT) · OpenF1 (free tier, non-commercial) · Jolpica F1 API · TracingInsights (Apache-2.0)
              </span>
            </Row>
          </section>
        </div>
        <div className="settings-col">
          <section className="panel" aria-label="Preview">
            <div className="panel-bar"><h2>Preview</h2><span className="panel-meta">A timing row and the header clock.</span></div>
            <div className={`settings-preview density-${settings.density}`}>
              <div className="preview-clock">
                <span>Header clock</span>
                <span className="display">{settings.clock === "race" ? "Lap 16 / 51 · 0:29:37" : "Lap 16 / 51"}</span>
              </div>
              <div className="preview-row"><span className="pos-chip num">1</span><span className="display code">RUS</span>
                <span className="num">{fast.value} {fast.unit}</span><span className="num">LEADER</span></div>
              <div className="preview-row"><span className="pos-chip num">3</span><span className="display code">VER</span>
                <span className="num">{fast2.value} {fast2.unit}</span><span className="num">+8.562</span></div>
            </div>
          </section>
          <section className="panel" aria-label="Keyboard shortcuts">
            <div className="panel-bar"><h2>Keyboard shortcuts</h2></div>
            <dl className="shortcuts">
              {SHORTCUTS.map(([key, what]) => (
                <div key={key}><dt><kbd>{key}</kbd></dt><dd>{what}</dd></div>
              ))}
            </dl>
          </section>
          <section className="panel" aria-label="Models">
            <div className="panel-bar"><h2>Models</h2><span className="panel-meta">Each replayed over past races it never saw.</span></div>
            <ul className="model-list">
              {MODELS.map((m) => (
                <li key={m.name}><b>{m.name}</b><span>{m.what}</span><span className="num model-score">{m.score}</span></li>
              ))}
            </ul>
          </section>
          <section className="panel" aria-label="About">
            <div className="panel-bar"><h2>About</h2></div>
            <p className="settings-about">
              Racecraft: an independent, non-commercial F1 replay and strategy workbench. Not affiliated with Formula 1,
              the FIA or any team. Copyright © 2026 Aditya Valaki, all rights reserved. It keeps no personal data and
              answers this computer only, unless opened to the network on purpose.
            </p>
          </section>
        </div>
      </main>
    </div>
  );
}

/**
 * What each model does and how it scored when replayed, each race predicted
 * only from what came before it. The figures are the replays' own, written up
 * in docs/TECHNICAL.md and the README; they change only when a replay is rerun.
 */
export const MODELS: readonly { name: string; what: string; score: string }[] = [
  { name: "Race prediction", what: "Finishing order and chances, from practice, qualifying and form", score: "0.69 v grid 0.66" },
  { name: "Sprint prediction", what: "The sprint, from sprint qualifying", score: "Brier 0.53 v 0.59" },
  { name: "Title odds", what: "The rest of the season simulated 10,000 times", score: "66% v 49% on the champion" },
  { name: "Pit crews", what: "Each crew's stops against each race's typical stop", score: "split-half r 0.80-0.91" },
  { name: "Race review", what: "Passes on track; places lost at each stop", score: "counts from timing" },
];
