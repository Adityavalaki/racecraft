import { useState } from "react";
import { api, type DataChoice } from "../api";

/**
 * shortcut: the times and sizes are words, from one connection on 2026-11-05 (practice about 2.5 minutes, a race
 * about 6, so about 16 a weekend; 1.6 GB and 445 sessions for all of 2023-2026), upgrade to figures from the
 * calendar when they drift.
 */
export const DATA_OPTIONS: readonly { id: DataChoice; label: string; title: string; cost: string; what: string }[] = [
  { id: "last5", label: "Last 5 races", title: "The last 5 races", cost: "About 1.5 hours · 100 MB",
    what: "Enough to replay recent races and see the latest predictions." },
  { id: "season", label: "Latest season", title: "The latest whole season", cost: "Up to 6.5 hours · 450 MB",
    what: "Every race this year, so season screens and models read the whole season." },
  { id: "everything", label: "Everything since 2023", title: "Everything since 2023", cost: "About 24 hours · 1.6 GB",
    what: "Every session on record since 2023, for the fullest history and comparisons." },
];

/**
 * The first thing a new install shows. Nothing downloads until one is picked (D-032), and it
 * cannot be dismissed, as there is nothing to look at behind it until then.
 */
export function DataChooser({ onChosen }: { onChosen: () => void }) {
  const [error, setError] = useState<string | null>(null);

  const pick = async (choice: DataChoice) => {
    try {
      await api.chooseData(choice);
      onChosen();
    } catch (e) {
      setError(String((e as Error).message ?? e));
    }
  };

  return (
    <div className="palette-backdrop chooser-backdrop">
      <div className="chooser" role="dialog" aria-modal="true" aria-labelledby="chooser-title">
        <h1 id="chooser-title" className="display">How much race data do you want?</h1>
        <p className="chooser-intro">
          Racecraft downloads it from free public sources, newest race first. You can use the app while it
          downloads, and each session appears as it arrives.
        </p>
        <div className="chooser-options">
          {DATA_OPTIONS.map((option, index) => (
            <button key={option.id} type="button" className="chooser-option" autoFocus={index === 0}
                    onClick={() => void pick(option.id)}>
              <span className="chooser-title display">{option.title}</span>
              <span className="chooser-cost num">{option.cost}</span>
              <span className="chooser-what">{option.what}</span>
            </button>
          ))}
        </div>
        {error && <p className="chooser-error" role="alert">Could not start: {error}</p>}
        <p className="chooser-note">
          It only downloads while Racecraft is open. Close it whenever you like: it carries on from where it stopped.
          You can get more later in Settings. Times are estimates and depend on your connection.
        </p>
      </div>
    </div>
  );
}
