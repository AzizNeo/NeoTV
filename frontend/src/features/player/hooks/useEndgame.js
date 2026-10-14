import { useEffect, useState } from 'react';

/** How long before the end the "next episode" card appears, when the episode has no credits marker. */
export const CREDITS_LEAD_S = 20;
const MIN_DURATION_S = 45; // a trailer or a clip has no "credits"

/**
 * Where an on-demand item is in its last moments (Netflix "post-play"):
 *   null       watching
 *   'credits'  the closing seconds: offer the next episode, keep playing
 *   'ended'    it finished: count down, then play the next one
 *
 * `creditsAt` (seconds) is the exact credits start when the catalogue knows it; otherwise the
 * last CREDITS_LEAD_S seconds. Seeking back before that point returns to null.
 */
export function useEndgame(video, { enabled, creditsAt = null, lead = CREDITS_LEAD_S }) {
  const [phase, setPhase] = useState(null);
  useEffect(() => {
    if (!video || !enabled) return undefined;
    const update = () => {
      if (video.ended) return setPhase('ended');
      const d = video.duration;
      if (!Number.isFinite(d) || d < MIN_DURATION_S) return setPhase(null);
      const start = creditsAt != null && creditsAt < d ? creditsAt : d - lead;
      setPhase(video.currentTime >= start ? 'credits' : null);
    };
    const events = ['timeupdate', 'seeked', 'ended', 'durationchange'];
    for (const e of events) video.addEventListener(e, update);
    return () => {
      for (const e of events) video.removeEventListener(e, update);
    };
  }, [video, enabled, creditsAt, lead]);
  return enabled ? phase : null;
}
