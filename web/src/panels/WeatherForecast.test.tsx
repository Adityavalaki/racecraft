import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WeatherForecast } from "./WeatherForecast";

function answer(body: unknown, ok = true) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok, status: ok ? 200 : 503, json: async () => body }));
}

afterEach(() => vi.unstubAllGlobals());

describe("WeatherForecast", () => {
  it("shows each session's forecast, saying when it is the archived one, with the credit", async () => {
    answer({
      event: "Singapore Grand Prix", circuit: "Marina Bay Street Circuit", credit: "Weather data by Open-Meteo.com",
      forecasts: [
        { session: "Race", starts_utc: "2026-10-11T12:00:00+00:00", upcoming: false, rain_chance: 39, rain_mm: 0,
          air_temp: 29.0, wind_kmh: 5.5 },
        { session: "Sprint", starts_utc: "2026-11-01T20:00:00+00:00", upcoming: true, rain_chance: 0, rain_mm: 0,
          air_temp: 23.6, wind_kmh: 5.6 },
      ],
    });
    render(<WeatherForecast sessionKey="2026_17_Q" />);
    await waitFor(() => expect(screen.getByLabelText("Weather forecast")).toBeTruthy());
    const text = screen.getByLabelText("Weather forecast").textContent ?? "";
    expect(text).toContain("Race was forecast: 39% chance of rain · 29 °C · wind 6 km/h");
    expect(text).toContain("Sprint forecast: 0% chance of rain");
    expect(text).toContain("Weather data by Open-Meteo.com");
  });

  it("shows nothing when no forecast can be had", async () => {
    answer({ detail: "Open-Meteo: unreachable" }, false);
    const { container } = render(<WeatherForecast sessionKey="2026_17_Q" />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container.textContent).toBe("");
  });
});
