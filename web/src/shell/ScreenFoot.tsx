import type { ReactNode } from "react";

/**
 * What a screen's figures rest on, and its notes, in one slim panel at the foot
 * of the screen (D-033). They used to sit above the figure row and below the
 * panels, so each screen's figures started at a different height and its
 * panels stopped short of the clock bar; now every screen reads header, figures,
 * panels, then this, the same way. `children` are the basis lines, as they were.
 */
export function ScreenFoot({ children, notes = [] }: { children?: ReactNode; notes?: string[] }) {
  if (!children && notes.length === 0) return null;
  return (
    <footer className="panel screen-foot" aria-label="What these figures rest on">
      {children}
      {notes.length > 0 && <ul className="prediction-notes">{notes.map((note) => <li key={note}>{note}</li>)}</ul>}
    </footer>
  );
}
