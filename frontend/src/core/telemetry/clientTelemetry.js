/**
 * Browser telemetry → POST /api/v1/kernel/client-events (our own endpoint; see the backend's
 * app/kernel/observability/client_telemetry.py for what is accepted and how it is scrubbed).
 *
 * - Web Vitals (LCP, INP, CLS, FCP, TTFB) from Google's `web-vitals`, as measured on real devices.
 * - Uncaught errors, unhandled promise rejections and React render errors (ErrorBoundary announces
 *   them with an `app:render-error` DOM event: shared/ stays free of core/ imports).
 * - Batched, sent with sendBeacon when the page is hidden or the queue fills (≤ 20 per call).
 * - Safe by construction: only the page *path* is sent (no query, no fragment), each distinct error
 *   once per page load, at most MAX_ERRORS per page load (a crash loop must not flood the API),
 *   and opaque cross-origin "Script error." reports are dropped (they carry nothing).
 * - Telemetry never disturbs the viewer: every failure here is swallowed.
 */
import { onCLS, onFCP, onINP, onLCP, onTTFB } from 'web-vitals';
import { api } from '@/core/api/client';

export const MAX_BATCH = 20;
export const MAX_ERRORS = 10;
const RELEASE = typeof __NEOTV_RELEASE__ === 'string' ? __NEOTV_RELEASE__ : null; // vite define

/** Pure state machine (unit-tested): what to send and when; the browser wiring is below. */
export function createReporter({ send, path = () => location.pathname, release = RELEASE } = {}) {
  let queue = [];
  const seen = new Set();
  let errors = 0;

  const flush = () => {
    if (!queue.length) return;
    const pending = queue;
    queue = [];
    for (let i = 0; i < pending.length; i += MAX_BATCH) {
      try {
        send(pending.slice(i, i + MAX_BATCH));
      } catch {
        /* telemetry must never break the page */
      }
    }
  };
  const push = (event) => {
    queue.push(event);
    if (queue.length >= MAX_BATCH) flush();
  };

  return {
    flush,
    pending: () => queue.length,
    vital: ({ name, value, rating }) => push({ kind: 'vital', name, value: Math.max(0, value), rating }),
    error: (source, error, { traceId } = {}) => {
      const message = String(error?.message ?? error ?? 'Unknown error').slice(0, 1000);
      if (message === 'Script error.' || message === 'Script error') return; // opaque cross-origin
      const stack = typeof error?.stack === 'string' ? error.stack.slice(0, 8000) : null;
      const key = `${source}|${message}|${stack?.split('\n', 2)[1] ?? ''}`;
      if (seen.has(key) || errors >= MAX_ERRORS) return;
      seen.add(key);
      errors += 1;
      const trace = traceId ?? error?.traceId ?? null; // ApiError carries the API call's trace id
      push({
        kind: 'error',
        source,
        message,
        stack,
        path: String(path()).slice(0, 500),
        trace_id: /^[0-9a-f]{32}$/.test(trace ?? '') ? trace : null,
        release,
      });
    },
  };
}

let started = false;

/** Wires the reporter into the page. Idempotent; call once at boot (main.jsx). */
export function startClientTelemetry() {
  if (started || typeof window === 'undefined') return;
  started = true;
  const reporter = createReporter({ send: (events) => api.beacon('kernel_client_events', { events }) });

  for (const subscribe of [onLCP, onINP, onCLS, onFCP, onTTFB]) subscribe(reporter.vital);
  window.addEventListener('error', (event) => {
    if (event.error || event.message) reporter.error('error', event.error ?? event.message);
  });
  window.addEventListener('unhandledrejection', (event) => reporter.error('unhandledrejection', event.reason));
  window.addEventListener('app:render-error', (event) => reporter.error('render', event.detail?.error));
  // `visibilitychange → hidden` is the last reliable moment on mobile; pagehide covers the rest.
  document.addEventListener('visibilitychange', () => document.visibilityState === 'hidden' && reporter.flush());
  window.addEventListener('pagehide', reporter.flush);
}
