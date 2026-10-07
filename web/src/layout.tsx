import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
  type ReactNode,
} from "react";

/**
 * The workspace: the track map in the middle, with the left column (session,
 * weather, driver cards, the feature launcher) and the leaderboard beside it.
 * The user sizes the two side columns by dragging; the map takes the rest.
 *
 * Every size is a percentage of the workspace, so a layout survives the
 * window being resized; `null` means "the default for this screen", which is
 * what a fresh install and a reset give. Each column keeps a floor in real
 * units, so nothing can be dragged too small to read, and the map never
 * shrinks below a size that still shows a circuit.
 */
export interface Layout {
  /** The left column's width, as a percentage of the workspace. */
  left: number | null;
  /** The leaderboard's width. */
  right: number | null;
}

export const DEFAULT_LAYOUT: Layout = { left: null, right: null };

// v2: the map-centred layout. A v1 layout sized panels that no longer exist.
const STORAGE_KEY = "racecraft:layout:v2";

/** Floors, in rem. */
const FLOOR = { left: 16, map: 20, right: 15 } as const;

/** A splitter's thickness, in px. Matches .splitter in styles.css. */
const SPLIT_PX = 6;

/** The layout saved by this browser, or the default. Never throws. */
export function loadLayout(): Layout {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null");
    if (!raw || typeof raw !== "object") return DEFAULT_LAYOUT;
    const saved = raw as Record<string, unknown>;
    const pick = (value: unknown) =>
      typeof value === "number" && Number.isFinite(value) && value > 0 && value < 100 ? value : null;
    return { left: pick(saved.left), right: pick(saved.right) };
  } catch {
    return DEFAULT_LAYOUT;
  }
}

function saveLayout(layout: Layout): void {
  try {
    if (isDefault(layout)) localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
  } catch {
    // Private windows and blocked storage: the layout simply is not remembered.
  }
}

export function isDefault(layout: Layout): boolean {
  return Object.values(layout).every((value) => value === null);
}

/** The layout, remembered in this browser, and a way back to the default. */
export function useLayout() {
  const [layout, setLayout] = useState<Layout>(loadLayout);
  useEffect(() => saveLayout(layout), [layout]);
  const reset = useCallback(() => setLayout(DEFAULT_LAYOUT), []);
  return { layout, setLayout, reset, customised: !isDefault(layout) };
}

/**
 * A size in px, held between its floor and the most the other panels leave,
 * as a percentage of `total`. The floor wins if the two cross, so a panel is
 * never asked to be smaller than it can draw.
 */
export function clampPercent(px: number, total: number, minPx: number, maxPx: number): number {
  if (!(total > 0)) return 50;
  const bounded = Math.min(Math.max(px, minPx), Math.max(minPx, maxPx));
  return (bounded / total) * 100;
}

function remPx(): number {
  return parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
}

/** The content box of an element: its rectangle less its padding. */
function contentBox(element: HTMLElement) {
  const rect = element.getBoundingClientRect();
  const style = getComputedStyle(element);
  const padLeft = parseFloat(style.paddingLeft) || 0;
  const padRight = parseFloat(style.paddingRight) || 0;
  const padTop = parseFloat(style.paddingTop) || 0;
  const padBottom = parseFloat(style.paddingBottom) || 0;
  return {
    left: rect.left + padLeft,
    right: rect.right - padRight,
    top: rect.top + padTop,
    width: rect.width - padLeft - padRight,
    height: rect.height - padTop - padBottom,
  };
}

interface SplitterProps {
  /** Which way the line runs: a vertical line is dragged sideways. */
  orientation: "vertical" | "horizontal";
  label: string;
  /** The size it controls, as a percentage, for assistive technology. */
  value: number | null;
  /** The pointer's position along the drag axis, in client px. */
  onMove: (position: number) => void;
  /** A keyboard nudge, in percentage points. */
  onStep: (points: number) => void;
  onReset: () => void;
}

/**
 * One draggable divider. Pointer capture keeps the drag going when the pointer
 * runs ahead of the line, over a canvas or off the window; the arrow keys move
 * it too (Shift for bigger steps), and a double-click puts it back.
 */
export function Splitter({ orientation, label, value, onMove, onStep, onReset }: SplitterProps) {
  const [dragging, setDragging] = useState(false);
  const back = orientation === "vertical" ? "ArrowLeft" : "ArrowUp";
  const forward = orientation === "vertical" ? "ArrowRight" : "ArrowDown";

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button > 0) return;              // primary button only
    event.preventDefault();                    // no text selection while dragging
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setDragging(true);
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!dragging) return;
    const position = orientation === "vertical" ? event.clientX : event.clientY;
    if (Number.isFinite(position)) onMove(position);   // never save NaN% into the layout
  };
  const stop = () => setDragging(false);
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== back && event.key !== forward) return;
    event.preventDefault();
    onStep((event.key === forward ? 1 : -1) * (event.shiftKey ? 5 : 1));
  };

  return (
    <div
      role="separator"
      tabIndex={0}
      aria-orientation={orientation}
      aria-label={label}
      aria-valuenow={value === null ? undefined : Math.round(value)}
      aria-valuemin={0}
      aria-valuemax={100}
      title={`${label} — drag to resize, double-click to reset`}
      className={`splitter splitter-${orientation}${dragging ? " is-dragging" : ""}`}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={stop}
      onPointerCancel={stop}
      onLostPointerCapture={stop}
      onDoubleClick={onReset}
      onKeyDown={onKeyDown}
    />
  );
}

interface WorkspaceProps {
  layout: Layout;
  onChange: (next: Layout) => void;
  left: ReactNode;
  map: ReactNode;
  right: ReactNode;
}

/** The three columns and the two splitters between them. */
export function Workspace({ layout, onChange, left, map, right }: WorkspaceProps) {
  const root = useRef<HTMLElement>(null);
  const leftCol = useRef<HTMLDivElement>(null);
  const rightCol = useRef<HTMLDivElement>(null);
  const width = (ref: { current: HTMLElement | null }) => ref.current?.getBoundingClientRect().width ?? 0;
  const span = () => (root.current ? contentBox(root.current).width : 0);

  // Each setter takes the width wanted in px and keeps the map above its floor.
  const setSide = (key: "left" | "right", other: { current: HTMLElement | null }, px: number) => {
    if (!root.current) return;
    const box = contentBox(root.current);
    const rem = remPx();
    const room = box.width - width(other) - FLOOR.map * rem - 2 * SPLIT_PX;
    onChange({ ...layout, [key]: clampPercent(px, box.width, FLOOR[key] * rem, room) });
  };

  const style = {
    ...(layout.left !== null && { "--left-w": `${layout.left}%` }),
    ...(layout.right !== null && { "--right-w": `${layout.right}%` }),
  } as CSSProperties;

  return (
    <main className="workspace" ref={root} style={style}>
      <div className="col col-left" ref={leftCol}>{left}</div>
      <Splitter
        orientation="vertical"
        label="Resize the left column"
        value={layout.left}
        onMove={(x) => root.current && setSide("left", rightCol, x - contentBox(root.current).left - SPLIT_PX / 2)}
        onStep={(points) => setSide("left", rightCol, width(leftCol) + (points / 100) * span())}
        onReset={() => onChange({ ...layout, left: null })}
      />
      <div className="col col-map">{map}</div>
      <Splitter
        orientation="vertical"
        label="Resize the leaderboard"
        value={layout.right}
        onMove={(x) => root.current && setSide("right", leftCol, contentBox(root.current).right - x - SPLIT_PX / 2)}
        onStep={(points) => setSide("right", leftCol, width(rightCol) - (points / 100) * span())}
        onReset={() => onChange({ ...layout, right: null })}
      />
      <div className="col col-right" ref={rightCol}>{right}</div>
    </main>
  );
}
