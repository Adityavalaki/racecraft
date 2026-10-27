import { memo, useRef, useState } from "react";
import { formatClock, type SessionInfo } from "../api";

interface Props {
  clips: SessionInfo["radio"];
  /** The replay clock: only clips already sent by then are listed. */
  t: number;
  start: number;
  codes: Record<number, string>;
}

/** How many of the latest clips are listed; the panel shares the column with race control. */
const SHOWN = 6;

/**
 * Team radio, newest first, as far as the replay has got (D-014). Each clip
 * plays from F1's own server; one plays at a time, and playing one stops the last.
 */
export const TeamRadio = memo(function TeamRadio({ clips, t, start, codes }: Props) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  if (!clips?.length) return null;
  const sent = clips.filter((clip) => clip.t <= t).slice(-SHOWN).reverse();

  const play = (url: string) => {
    const player = audio.current;
    if (!player) return;
    if (playing === url) {
      player.pause();
      setPlaying(null);
      return;
    }
    setFailed(null);
    player.src = url;
    player.play().then(() => setPlaying(url)).catch(() => {
      setPlaying(null);
      setFailed(url);
    });
  };

  return (
    <section className="panel team-radio" aria-label="Team radio">
      <div className="panel-bar">
        <h2>Team radio</h2>
        <span className="panel-meta">{clips.length} clips</span>
      </div>
      {/* One player for the panel; the clip ending clears its button. */}
      <audio ref={audio} onEnded={() => setPlaying(null)} preload="none" />
      {sent.length === 0 ? (
        <p className="empty">No team radio yet.</p>
      ) : (
        <ol className="rc-rows">
          {sent.map((clip) => {
            const who = codes[clip.driver_number] ?? String(clip.driver_number);
            const isPlaying = playing === clip.url;
            return (
              <li key={clip.url} className="rc-row">
                <span className="rc-when num">{formatClock(clip.t - start)}</span>
                <button type="button" className="radio-play" onClick={() => play(clip.url)}
                        aria-label={`${isPlaying ? "Stop" : "Play"} ${who}'s radio at ${formatClock(clip.t - start)}`}>
                  {isPlaying ? "■" : "▶"}
                </button>
                <span className="rc-text">
                  {who}
                  {failed === clip.url && <span className="rc-tag is-red">could not play</span>}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
});
