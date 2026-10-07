import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import { DEFAULT_LAYOUT, Workspace, clampPercent, loadLayout, useLayout, type Layout } from "./layout";

const KEY = "racecraft:layout:v2";

/** A workspace with its layout held the way App holds it, so saving is real too. */
function Harness() {
  const { layout, setLayout, reset, customised } = useLayout();
  return (
    <>
      {customised && <button onClick={reset}>Reset layout</button>}
      <Workspace layout={layout} onChange={setLayout}
                 left={<div>left</div>} map={<div>map</div>} right={<div>leaderboard</div>} />
    </>
  );
}

/**
 * jsdom lays nothing out, so every box is 0x0. Give the workspace and its
 * columns the sizes a 1400px window would: left column 320, leaderboard 300.
 */
function fakeLayoutBoxes() {
  const box = (left: number, width: number) =>
    ({ left, top: 0, width, height: 800, right: left + width, bottom: 800, x: left, y: 0, toJSON() {} }) as DOMRect;
  return vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    if (this.classList.contains("workspace")) return box(0, 1400);
    if (this.classList.contains("col-left")) return box(0, 320);
    if (this.classList.contains("col-right")) return box(1100, 300);
    if (this.classList.contains("col-map")) return box(326, 768);
    return box(0, 0);
  });
}

const splitter = (name: RegExp) => screen.getByRole("separator", { name });

// jsdom has no PointerEvent, and its stand-in drops clientX. A MouseEvent
// carries the coordinates and the button, which is all the splitter reads.
beforeAll(() => {
  if (typeof window.PointerEvent === "undefined") {
    class PointerEventShim extends MouseEvent {
      pointerId: number;
      constructor(type: string, init: PointerEventInit = {}) {
        super(type, init);
        this.pointerId = init.pointerId ?? 0;
      }
    }
    window.PointerEvent = PointerEventShim as unknown as typeof PointerEvent;
  }
});

beforeEach(() => localStorage.clear());
afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe("clampPercent", () => {
  it("turns px into a share of the whole", () => {
    expect(clampPercent(350, 1400, 100, 1000)).toBe(25);
  });
  it("never goes below the floor or above what the others leave", () => {
    expect(clampPercent(10, 1000, 200, 800)).toBe(20);
    expect(clampPercent(990, 1000, 200, 800)).toBe(80);
  });
  it("lets the floor win when the room is smaller than it", () => {
    expect(clampPercent(500, 1000, 300, 100)).toBe(30);
  });
  it("does not divide by zero before anything is laid out", () => {
    expect(clampPercent(100, 0, 10, 50)).toBe(50);
  });
});

describe("loadLayout", () => {
  it("gives the defaults when nothing is saved", () => {
    expect(loadLayout()).toEqual(DEFAULT_LAYOUT);
  });
  it("restores a saved layout", () => {
    const saved: Layout = { left: 24, right: 20 };
    localStorage.setItem(KEY, JSON.stringify(saved));
    expect(loadLayout()).toEqual(saved);
  });
  it("drops anything that is not a sensible percentage", () => {
    localStorage.setItem(KEY, JSON.stringify({ left: 140, right: "big" }));
    expect(loadLayout()).toEqual({ left: null, right: null });
  });
  it("ignores a layout saved for the old five-panel screen", () => {
    localStorage.setItem("racecraft:layout:v1", JSON.stringify({ tower: 45, right: 20, map: 50, stewards: 30 }));
    expect(loadLayout()).toEqual(DEFAULT_LAYOUT);
  });
  it("survives storage it cannot read", () => {
    localStorage.setItem(KEY, "{not json");
    expect(loadLayout()).toEqual(DEFAULT_LAYOUT);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(loadLayout()).toEqual(DEFAULT_LAYOUT);
  });
});

describe("Workspace", () => {
  it("puts the map between two labelled, keyboard-reachable splitters", () => {
    const { container } = render(<Harness />);
    const columns = Array.from(container.querySelector(".workspace")!.children).map((c) => c.className);
    expect(columns).toEqual(["col col-left", "splitter splitter-vertical", "col col-map",
                             "splitter splitter-vertical", "col col-right"]);
    for (const each of screen.getAllByRole("separator")) {
      expect(each.getAttribute("aria-orientation")).toBe("vertical");
      expect(each.getAttribute("tabindex")).toBe("0");
    }
    expect(splitter(/left column/i)).toBeDefined();
    expect(splitter(/leaderboard/i)).toBeDefined();
  });

  it("follows the pointer while dragging, and never squeezes the map below its floor", () => {
    fakeLayoutBoxes();
    render(<Harness />);
    const left = splitter(/left column/i);

    fireEvent.pointerDown(left, { button: 0, pointerId: 1, clientX: 320 });
    fireEvent.pointerMove(left, { pointerId: 1, clientX: 703 });  // 700px of 1400
    expect(left.getAttribute("aria-valuenow")).toBe("50");

    // Far left: held at the column's 16rem floor (256px of 1400 = 18%).
    fireEvent.pointerMove(left, { pointerId: 1, clientX: 5 });
    expect(left.getAttribute("aria-valuenow")).toBe("18");

    // Far right: held where the map keeps its 20rem and the leaderboard its 300px.
    fireEvent.pointerMove(left, { pointerId: 1, clientX: 1395 });
    expect(left.getAttribute("aria-valuenow")).toBe("55");         // (1400-300-320-12)/1400

    fireEvent.pointerUp(left, { pointerId: 1 });
    fireEvent.pointerMove(left, { pointerId: 1, clientX: 703 });   // released: no longer follows
    expect(left.getAttribute("aria-valuenow")).toBe("55");
  });

  it("sets the widths as custom properties the stylesheet reads", () => {
    fakeLayoutBoxes();
    const { container } = render(<Harness />);
    const workspace = container.querySelector(".workspace") as HTMLElement;
    expect(workspace.style.getPropertyValue("--left-w")).toBe("");   // default: CSS decides
    const left = splitter(/left column/i);
    fireEvent.pointerDown(left, { button: 0, pointerId: 1 });
    fireEvent.pointerMove(left, { pointerId: 1, clientX: 703 });
    expect(workspace.style.getPropertyValue("--left-w")).toBe("50%");
  });

  it("moves with the arrow keys, Shift for bigger steps, each splitter its own way", () => {
    fakeLayoutBoxes();
    render(<Harness />);
    const left = splitter(/left column/i);
    fireEvent.keyDown(left, { key: "ArrowRight" });                 // 320px + 1% of 1400
    expect(left.getAttribute("aria-valuenow")).toBe("24");
    fireEvent.keyDown(left, { key: "ArrowLeft", shiftKey: true });  // 320px - 5%: at the floor
    expect(left.getAttribute("aria-valuenow")).toBe("18");

    const right = splitter(/leaderboard/i);
    fireEvent.keyDown(right, { key: "ArrowLeft" });                 // the line moves left: wider
    expect(right.getAttribute("aria-valuenow")).toBe("22");         // 300px + 1% of 1400
  });

  it("remembers the layout, and a double-click puts one splitter back", () => {
    fakeLayoutBoxes();
    const first = render(<Harness />);
    fireEvent.keyDown(splitter(/leaderboard/i), { key: "ArrowLeft" });
    expect(JSON.parse(localStorage.getItem(KEY)!).right).toBeGreaterThan(0);
    first.unmount();

    render(<Harness />);                                            // a fresh start keeps it
    expect(splitter(/leaderboard/i).getAttribute("aria-valuenow")).not.toBeNull();

    fireEvent.doubleClick(splitter(/leaderboard/i));
    expect(splitter(/leaderboard/i).getAttribute("aria-valuenow")).toBeNull();
    expect(localStorage.getItem(KEY)).toBeNull();                  // all default again: nothing kept
  });

  it("offers a reset once anything has moved, and the reset clears everything", () => {
    fakeLayoutBoxes();
    render(<Harness />);
    expect(screen.queryByRole("button", { name: "Reset layout" })).toBeNull();

    fireEvent.keyDown(splitter(/left column/i), { key: "ArrowRight" });
    fireEvent.keyDown(splitter(/leaderboard/i), { key: "ArrowLeft" });
    fireEvent.click(screen.getByRole("button", { name: "Reset layout" }));

    expect(screen.queryByRole("button", { name: "Reset layout" })).toBeNull();
    for (const each of screen.getAllByRole("separator")) expect(each.getAttribute("aria-valuenow")).toBeNull();
  });
});

describe("useLayout when storage is blocked", () => {
  it("still lets the user drag; it just is not remembered", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    fakeLayoutBoxes();
    render(<Harness />);
    fireEvent.keyDown(splitter(/left column/i), { key: "ArrowRight" });
    expect(splitter(/left column/i).getAttribute("aria-valuenow")).toBe("24");
  });
});
