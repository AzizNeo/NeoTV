import { useEffect } from 'react';

/**
 * Media Session API: the OS knows what is playing — title and artwork on the lock screen and
 * notification, and hardware media keys / headset buttons / the PiP window's ⏭ work.
 * Every action is optional: unsupported ones throw and are skipped.
 */
export function useMediaSession(video, { title, subtitle, artwork, isLive, onNext, onPrev }) {
  useEffect(() => {
    const session = typeof navigator !== 'undefined' ? navigator.mediaSession : undefined;
    if (!session || !video) return undefined;
    try {
      session.metadata = new window.MediaMetadata({
        title: subtitle ?? title,
        artist: subtitle ? title : 'NeoTV',
        album: 'NeoTV',
        artwork: artwork ? [{ src: new URL(artwork, window.location.href).href }] : [],
      });
    } catch {
      /* MediaMetadata unsupported */
    }
    const seek = (to) => {
      if (Number.isFinite(video.duration)) video.currentTime = Math.max(0, Math.min(video.duration, to));
    };
    const handlers = {
      play: () => video.play().catch(() => {}),
      pause: () => video.pause(),
      seekbackward: isLive ? null : (d) => seek(video.currentTime - (d.seekOffset ?? 10)),
      seekforward: isLive ? null : (d) => seek(video.currentTime + (d.seekOffset ?? 10)),
      seekto: isLive ? null : (d) => seek(d.seekTime),
      nexttrack: onNext ?? null,
      previoustrack: onPrev ?? null,
    };
    const set = (action, fn) => {
      try {
        session.setActionHandler(action, fn);
      } catch {
        /* action not supported by this browser */
      }
    };
    for (const [action, fn] of Object.entries(handlers)) set(action, fn);
    return () => {
      for (const action of Object.keys(handlers)) set(action, null);
      session.metadata = null;
    };
  }, [video, title, subtitle, artwork, isLive, onNext, onPrev]);
}
