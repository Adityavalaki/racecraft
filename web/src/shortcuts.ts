import { useEffect, useRef } from "react";

export interface ShortcutActions {
  toggle: () => void;
  nudge: (seconds: number) => void;
  faster: () => void;
  slower: () => void;
  toStart: () => void;
  toggleNames: () => void;
  toggleDrs: () => void;
}

/** What each key does, for the legend on screen. */
export const SHORTCUTS: readonly [string, string][] = [
  ["Space", "Play / pause"],
  ["← →", "Back / forward 5 s (Shift: 30 s)"],
  ["↑ ↓", "Faster / slower"],
  ["Home", "Back to the start"],
  ["L", "Driver names on the map"],
  ["D", "DRS zones on the map (2026: overtake mode)"],
];

/** Where typing means typing: a key there is the field's, not a shortcut. */
function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (target.closest("input, select, textarea")) return true;
  return target.getAttribute("role") === "separator";   // the arrows resize panels there
}

/**
 * The replay's keyboard: Space plays and pauses wherever focus is (it would
 * otherwise click whichever button was last pressed); the arrows step and
 * change speed; L and D toggle the map's names and DRS zones. Nothing fires
 * while typing in a field, or on a splitter, whose arrows resize the panels.
 */
export function useShortcuts(actions: ShortcutActions, enabled = true): void {
  const act = useRef(actions);
  act.current = actions;

  useEffect(() => {
    if (!enabled) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.ctrlKey || event.metaKey || event.altKey || isTyping(event.target)) return;
      const run = act.current;
      const step = event.shiftKey ? 30 : 5;
      const handlers: Record<string, () => void> = {
        " ": run.toggle,
        ArrowLeft: () => run.nudge(-step),
        ArrowRight: () => run.nudge(step),
        ArrowUp: run.faster,
        ArrowDown: run.slower,
        Home: run.toStart,
        l: run.toggleNames,
        L: run.toggleNames,
        d: run.toggleDrs,
        D: run.toggleDrs,
      };
      const handler = handlers[event.key];
      if (!handler) return;
      event.preventDefault();                        // no page scroll, no button press
      handler();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);
}
