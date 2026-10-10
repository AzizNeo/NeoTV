/**
 * One playback session = one stream slot on the server (FE-02: VOD and live go
 * through the same gate; the player only ever sees `manifest_url`).
 *
 * Lifecycle: open → heartbeat every `heartbeat_interval_s` → release on
 * unmount/close/pagehide (sendBeacon; the token itself is the credential).
 */
import { useEffect, useRef, useState } from 'react';
import { api } from '@/core/api/client';

export function usePlaybackSession(contentRef) {
  // State is tagged with the contentRef it belongs to; a new ref reads as 'opening'
  // until its own result lands (no synchronous reset inside the effect).
  const [state, setState] = useState({ ref: null, status: 'idle', session: null, error: null });
  const tokenRef = useRef(null);

  useEffect(() => {
    if (!contentRef) return undefined;
    const controller = new AbortController();
    let timer = null;

    const release = () => {
      const token = tokenRef.current;
      if (!token) return;
      tokenRef.current = null;
      api.beacon('playback_release', { session_token: token });
    };

    api
      .call('playback_open_session', { body: { content_ref: contentRef }, signal: controller.signal })
      .then((session) => {
        tokenRef.current = session.session_token;
        if (controller.signal.aborted) {
          release();
          return;
        }
        setState({ ref: contentRef, status: 'ready', session, error: null });
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
        setState({ ref: contentRef, status: 'denied', session: null, error });
      });

    window.addEventListener('pagehide', release);
    return () => {
      controller.abort();
      clearInterval(timer);
      window.removeEventListener('pagehide', release);
      release();
    };
  }, [contentRef]);

  if (!contentRef) return IDLE;
  if (state.ref !== contentRef) return OPENING;
  return state;
}

const IDLE = Object.freeze({ status: 'idle', session: null, error: null });
const OPENING = Object.freeze({ status: 'opening', session: null, error: null });
