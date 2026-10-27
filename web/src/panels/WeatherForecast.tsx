import { useEffect, useState } from "react";
import { api, type WeekendForecast } from "../api";

/**
 * The weather expected at the start of the weekend's race and sprint (D-015),
 * above the prediction. Display only: no model uses it. For a weekend already
 * run it is the forecast as it stood then, which is said, because what actually
 * happened is in the session's own weather. Nothing is shown if Open-Meteo or
 * Jolpica cannot be reached: it is an extra, never in the way.
 */
export function WeatherForecast({ sessionKey }: { sessionKey: string }) {
  const [forecast, setForecast] = useState<WeekendForecast | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setForecast(null);
    api.forecast(sessionKey, controller.signal).then(setForecast).catch(() => undefined);
    return () => controller.abort();
  }, [sessionKey]);

  // An error body is JSON too, so the shape is checked rather than assumed.
  if (!Array.isArray(forecast?.forecasts) || forecast.forecasts.length === 0) return null;
  return (
    <div className="forecast" aria-label="Weather forecast">
      {forecast.forecasts.map((f) => (
        <span key={f.session} className="forecast-item">
          <b>{f.session}</b>
          {f.upcoming ? " forecast: " : " was forecast: "}
          {f.rain_chance != null && `${f.rain_chance}% chance of rain`}
          {f.air_temp != null && ` · ${Math.round(f.air_temp)} °C`}
          {f.wind_kmh != null && ` · wind ${Math.round(f.wind_kmh)} km/h`}
        </span>
      ))}
      <span className="forecast-credit">{forecast.credit}</span>
    </div>
  );
}
