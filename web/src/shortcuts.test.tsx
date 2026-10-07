import { fireEvent, render, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useShortcuts, type ShortcutActions } from "./shortcuts";

function actions() {
  return {
    toggle: vi.fn(), nudge: vi.fn<(seconds: number) => void>(), faster: vi.fn(), slower: vi.fn(),
    toStart: vi.fn(), toggleNames: vi.fn(), toggleDrs: vi.fn(),
  } satisfies ShortcutActions;
}

const press = (key: string, options: KeyboardEventInit = {}, target: Element = document.body) =>
  fireEvent.keyDown(target, { key, ...options });

describe("keyboard shortcuts", () => {
  it("plays, steps, changes speed and toggles the map", () => {
    const act = actions();
    renderHook(() => useShortcuts(act));
    press(" ");
    press("ArrowLeft");
    press("ArrowRight", { shiftKey: true });
    press("ArrowUp");
    press("ArrowDown");
    press("Home");
    press("l");
    press("D");
    expect(act.toggle).toHaveBeenCalledTimes(1);
    expect(act.nudge.mock.calls).toEqual([[-5], [30]]);
    expect(act.faster).toHaveBeenCalledTimes(1);
    expect(act.slower).toHaveBeenCalledTimes(1);
    expect(act.toStart).toHaveBeenCalledTimes(1);
    expect(act.toggleNames).toHaveBeenCalledTimes(1);
    expect(act.toggleDrs).toHaveBeenCalledTimes(1);
  });

  it("keeps Space from also pressing the button that has focus", () => {
    renderHook(() => useShortcuts(actions()));
    const { getByRole } = render(<button type="button">VER</button>);
    const event = new KeyboardEvent("keydown", { key: " ", bubbles: true, cancelable: true });
    getByRole("button").dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("leaves keys alone while typing, on a splitter, or with a modifier held", () => {
    const act = actions();
    renderHook(() => useShortcuts(act));
    const { container } = render(
      <div>
        <input aria-label="search" />
        <select aria-label="session"><option>a</option></select>
        <div role="separator" tabIndex={0} />
      </div>,
    );
    press(" ", {}, container.querySelector("input")!);
    press("ArrowLeft", {}, container.querySelector("select")!);
    press("ArrowRight", {}, container.querySelector("[role=separator]")!);
    press("l", { ctrlKey: true });
    press("ArrowLeft", { altKey: true });
    for (const fn of Object.values(act)) expect(fn).not.toHaveBeenCalled();
  });

  it("does nothing while switched off, as before a session has loaded", () => {
    const act = actions();
    renderHook(() => useShortcuts(act, false));
    press(" ");
    expect(act.toggle).not.toHaveBeenCalled();
  });
});
