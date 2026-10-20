/**
 * One playback session = one stream slot on the server (FE-02: VOD and live go
 * through the same gate; the player only ever sees `manifest_url`).
 *
 * Lifecycle: open → heartbeat every `heartbeat_interval_s` → release on
 * unmount/close/pagehide (sendBeacon; the token itself is the credential).
 *
 * `archiveWindow` ({ start, end }, ISO strings) plays a stretch of a live channel's archive instead of the
 * live stream — catch-up and start over (ADR-0012). The server decides whether it is allowed.
 */
import { useEffect, useRef, useState } from 'react';
import { api } from '@/core/api/client';

export function usePlaybackSession(contentRef, archiveWindow = null) {
  // One key for what is opened: the same channel live and from its archive are different sessions.
  const key = contentRef ? [contentRef, archiveWindow?.start ?? '', archiveWindow?.end ?? ''].join('|') : null;
  // State is tagged with the contentRef it belongs to; a new ref reads as 'opening'
  // until its own result lands (no synchronous reset inside the effect).
  const [state, setState] = useState({ ref: null, status: 'idle', session: null, error: null });
  const tokenRef = useRef(null);

  useEffect(() => {
    if (!key) return undefined;
    const body = {
      content_ref: contentRef,
      ...(archiveWindow ? { window: { start: archiveWindow.start, end: archiveWindow.end } } : {}),
    };
    const controller = new AbortController();
    let timer = null;

    const release = () => {
      const token = tokenRef.current;
      if (!token) return;
      tokenRef.current = null;
      api.beacon('playback_release', { session_token: token });
    };

    // Opened on the next tick, not synchronously: an effect that is set up and torn down at once
    // (React StrictMode, a fast re-render) must not reach the server. An aborted fetch still lands
    // there, and the server would let that phantom session replace the real one (same device).
    const open = () =>
      api
        .call('playback_open_session', { body, signal: controller.signal })
        .then((session) => {
          tokenRef.current = session.session_token;
          if (controller.signal.aborted) {
            release();
            return;
          }
          setState({ ref: key, status: 'ready', session, error: null });
          timer = setInterval(() => {
            api
              .call('playback_heartbeat', { body: { session_token: session.session_token } })
              .catch((error) => {
                if (error?.status >= 400 && error?.status < 500) {
                  clearInterval(timer);
                  tokenRef.current = null;
                  setState((s) => ({ ...s, status: 'expired', error }));
                } // transient (5xx / network): keep the stream, retry next tick
              });
          }, Math.max(5, session.heartbeat_interval_s) * 1000);
        })
        .catch((error) => {
          if (error?.name === 'AbortError') return;
          setState({ ref: key, status: 'denied', session: null, error });
        });

    const pending = setTimeout(open, 0);

    window.addEventListener('pagehide', release);
    return () => {
      clearTimeout(pending);
      controller.abort();
      clearInterval(timer);
      window.removeEventListener('pagehide', release);
      release();
    };
    // `archiveWindow` is read through `key` (its start and end are part of it): no re-open for an equal one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  if (!key) return IDLE;
  if (state.ref !== key) return OPENING;
  return state;
}

const IDLE = Object.freeze({ status: 'idle', session: null, error: null });
const OPENING = Object.freeze({ status: 'opening', session: null, error: null });
