import type { ReactNode } from "react";
import { screenById } from "../features";
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
            <div className="panel-bar"><h2>Data</h2><span className="panel-meta">Racecraft reads race data through FastF1.</span></div>
            <Row title="Latest weekends" hint="Refresh fetches anything from the five most recent race weekends not on this device yet.">
              <SyncButton onSynced={onSynced} />
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
        </div>
      </main>
    </div>
  );
}
