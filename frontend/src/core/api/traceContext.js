/**
 * W3C Trace Context for API calls: each call gets a fresh trace id, sent as `traceparent`, so the
 * API continues *this* trace — and a failed call can be matched with the backend trace and logs.
 *
 * No OpenTelemetry SDK in the browser (bundle size, CSP): we only mint ids. The flags are `00`:
 * the browser does not decide sampling — the server does (and ignores a caller's decision anyway).
 */
const hex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');

function randomHex(byteCount) {
  const bytes = crypto.getRandomValues(new Uint8Array(byteCount));
  // All-zero ids are invalid in W3C Trace Context; astronomically unlikely, but never send one.
  if (bytes.every((b) => b === 0)) bytes[byteCount - 1] = 1;
  return hex(bytes);
}

/** `{ traceId, header }` — header = `00-<32 hex trace id>-<16 hex parent id>-00`. */
export function newTraceContext() {
  const traceId = randomHex(16);
  return { traceId, header: `00-${traceId}-${randomHex(8)}-00` };
}
