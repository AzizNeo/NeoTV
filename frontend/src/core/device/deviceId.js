/**
 * Stable per-browser device id → `X-Device-ID`. The backend derives an HMAC
 * device key from (user, this id); it is an identifier, not a credential.
 */
const KEY = 'neotv.device_id';
let memoryFallback = null;

function generate() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  return `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}-dev`;
}

export function deviceId() {
  try {
    let id = localStorage.getItem(KEY);
    if (!id) {
      id = generate();
      localStorage.setItem(KEY, id);
    }
    return id;
  } catch {
    memoryFallback ??= generate();
    return memoryFallback;
  }
}
