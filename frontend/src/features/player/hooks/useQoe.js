/** Quality-of-experience probe: startup time, rebuffering, watch time → playback_qoe on close. */
import { useEffect, useRef } from 'react';
import { api } from '@/core/api/client';

function deviceType() {
  const ua = navigator.userAgent.toLowerCase();
  if (/smart-tv|smarttv|web0s|tizen|hbbtv/.test(ua)) return 'tv';
  if (/ipad|tablet/.test(ua) || (ua.includes('android') && !ua.includes('mobile'))) return 'tablet';
  if (/mobile|iphone/.test(ua)) return 'mobile';
  return 'desktop';
}

export function useQoe(videoRef, { contentRef, sessionToken, engineRef }) {
  const stats = useRef(null);

  useEffect(() => {
    // The ref (not its value) is captured on purpose: the engine may be swapped
    // mid-session and the final report must read the one playing at teardown.
    const engineHolder = engineRef;
    const video = videoRef.current;
    if (!video || !sessionToken) return undefined;
    const s = { openedAt: performance.now(), startup: null, rebuffers: 0, rebufferMs: 0, stallAt: null, watched: 0, lastTick: null };
    stats.current = s;

    const onPlaying = () => {
      if (s.startup === null) s.startup = Math.round(performance.now() - s.openedAt);
      if (s.stallAt !== null) {
        s.rebufferMs += performance.now() - s.stallAt;
        s.stallAt = null;
      }
      s.lastTick = performance.now();
    };
    const onWaiting = () => {
      if (s.startup !== null && s.stallAt === null) {
        s.rebuffers += 1;
        s.stallAt = performance.now();
      }
    };
    const onTime = () => {
      const now = performance.now();
      if (s.lastTick !== null && !video.paused) s.watched += (now - s.lastTick) / 1000;
      s.lastTick = now;
    };
    video.addEventListener('playing', onPlaying);
    video.addEventListener('waiting', onWaiting);
    video.addEventListener('timeupdate', onTime);

    return () => {
      video.removeEventListener('playing', onPlaying);
      video.removeEventListener('waiting', onWaiting);
      video.removeEventListener('timeupdate', onTime);
      if (s.startup === null && s.watched < 1) return; // never started: nothing meaningful to report
      const engineStats = engineHolder.current?.stats?.() ?? {};
      api
        .call('playback_record_qoe', {
          body: {
            content_ref: contentRef,
            session_token: sessionToken,
            startup_time_ms: s.startup,
            rebuffer_count: s.rebuffers,
            rebuffer_duration_ms: Math.round(s.rebufferMs),
            watch_duration_s: Math.round(s.watched),
            bitrate_kbps: engineStats.bitrateKbps ?? null,
            resolution: engineStats.resolution ?? null,
            device_type: deviceType(),
            connection_type: navigator.connection?.effectiveType ?? null,
          },
        })
        .catch(() => {}); // telemetry must never disturb the user
    };
  }, [videoRef, contentRef, sessionToken, engineRef]);
}
