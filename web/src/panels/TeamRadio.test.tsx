import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TeamRadio } from "./TeamRadio";

const CLIPS = [
  { driver_number: 12, t: 100, url: "https://livetiming.formula1.com/static/ANT_1.mp3" },
  { driver_number: 87, t: 200, url: "https://livetiming.formula1.com/static/BEA_1.mp3" },
  { driver_number: 1, t: 900, url: "https://livetiming.formula1.com/static/NOR_1.mp3" },
];
const CODES = { 12: "ANT", 87: "BEA", 1: "NOR" };

describe("TeamRadio", () => {
  it("lists only the clips sent by the replay clock, newest first", () => {
    render(<TeamRadio clips={CLIPS} t={300} start={0} codes={CODES} />);
    const rows = screen.getAllByRole("listitem").map((row) => row.textContent);
    expect(rows[0]).toContain("BEA");
    expect(rows[1]).toContain("ANT");
    expect(rows).toHaveLength(2);                       // NOR's, at 900 s, is not sent yet
  });

  it("plays a clip and stops it on a second press", async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    render(<TeamRadio clips={CLIPS} t={300} start={0} codes={CODES} />);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: /Play BEA's radio/ })));
    expect(play).toHaveBeenCalledTimes(1);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: /Stop BEA's radio/ })));
    expect(pause).toHaveBeenCalled();
    play.mockRestore();
    pause.mockRestore();
  });

  it("says so when a clip cannot be played", async () => {
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockRejectedValue(new Error("blocked"));
    render(<TeamRadio clips={CLIPS} t={300} start={0} codes={CODES} />);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: /Play ANT's radio/ })));
    expect(screen.getByText("could not play")).toBeTruthy();
    play.mockRestore();
  });

  it("is not shown for a session without radio", () => {
    const { container } = render(<TeamRadio clips={[]} t={300} start={0} codes={CODES} />);
    expect(container.textContent).toBe("");
  });
});
