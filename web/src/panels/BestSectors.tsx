import { memo } from "react";
import { formatLapTime, formatSector, type BestSector } from "../api";

interface Props {
  sectors: BestSector[];
  idealLap: number | null;
  fastestLap: number | null;
}

/**
 * Who holds each sector, and the lap they would add up to.
 *
 * The ideal lap is a lap nobody has driven: the three quickest sectors of the
 * session strung together. The gap between it and the fastest real lap is how
 * much time is sitting on the table.
 */
export const BestSectors = memo(function BestSectors({ sectors, idealLap, fastestLap }: Props) {
  const untapped = idealLap !== null && fastestLap !== null ? fastestLap - idealLap : null;
  return (
    <div className="best-sectors">
      {sectors.map((sector) => (
        <div className="best-sector" key={sector.sector}>
          <span className="bs-label">S{sector.sector}</span>
          <span className="bs-time">{formatSector(sector.seconds)}</span>
          <span className="bs-driver">{sector.driver ?? "—"}</span>
        </div>
      ))}
      <div className="best-sector is-ideal">
        <span className="bs-label">IDEAL</span>
        <span className="bs-time">{formatLapTime(idealLap)}</span>
        <span className="bs-driver">
          {untapped !== null && untapped > 0.0005 ? `−${untapped.toFixed(3)}` : "on the lap"}
        </span>
      </div>
    </div>
  );
});
