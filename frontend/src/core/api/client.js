/**
 * The ONE HTTP client. Features never write URLs: they call operations by the
 * backend's OpenAPI operationId (`api.call('billing_checkout', …)`), which
 * `npm run check:api` verifies against the committed contract.
 *
 * * Envelope `{success, data}` is unwrapped; errors become ApiError(code).
 * * Access token in memory; on 401 TOKEN_EXPIRED a single-flight refresh (httpOnly
 *   cookie + CSRF header) runs and the request is retried once.
 * * 401 on profile context → `profile:reselect` event (not a logout).
 * * Media is never fetched through here (signed URLs carry their own grant).
 */
import { env } from '@/core/config/env';
import { tokenStore } from '@/core/auth/tokenStore';
import { deviceId } from '@/core/device/deviceId';
import { ApiError } from './ApiError';
import { OPERATIONS } from './contract.generated';

const CSRF = { 'X-Requested-With': 'XMLHttpRequest' };
let refreshing = null;

export class UnknownOperationError extends Error {
  constructor(id) {
    super(`Unknown API operation '${id}' — regenerate the contract (npm run gen:api)`);
    this.name = 'UnknownOperationError';
  }
}

function operation(id) {
  const op = OPERATIONS[id];
  if (!op) throw new UnknownOperationError(id);
  return op;
}

function buildUrl(id, params = {}, query = undefined) {
  const op = operation(id);
  const path = op.path.replace(/\{(\w+)\}/g, (_m, name) => {
    if (params[name] === undefined || params[name] === null) {
      throw new Error(`Missing path parameter '${name}' for ${id}`);
    }
    return encodeURIComponent(String(params[name]));
  });
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value));
  }
  const qs = search.toString();
  return `${env.VITE_API_BASE_URL}${path}${qs ? `?${qs}` : ''}`;
}

async function unwrap(response) {
  if (response.status === 204) return null;
  const body = await response.json().catch(() => null);
  return body && typeof body === 'object' && 'success' in body ? body.data : body;
}

async function refreshAccess() {
  refreshing ??= fetch(buildUrl('identity_refresh'), { method: 'POST', credentials: 'include', headers: CSRF })
    .then(async (response) => {
      if (!response.ok) throw await ApiError.fromResponse(response);
      const data = await unwrap(response);
      tokenStore.setAccess(data.access_token);
      return data;
    })
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

function idempotencyKey() {
  return globalThis.crypto?.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
}

async function call(id, { params, query, body, headers, signal, rawBody, contentType, retry = true } = {}) {
  const op = operation(id);
  const finalHeaders = { 'X-Device-ID': deviceId(), ...CSRF, ...(headers ?? {}) };
  const access = tokenStore.getAccess();
  if (access && op.auth !== 'public') finalHeaders.Authorization = `Bearer ${access}`;
  const profile = tokenStore.getProfile();
  if (profile && op.auth !== 'public') finalHeaders['X-Profile-Token'] = profile;
  if (op.idempotent && !finalHeaders['Idempotency-Key']) finalHeaders['Idempotency-Key'] = idempotencyKey();

  let payload;
  if (rawBody !== undefined) {
    payload = rawBody;
    if (contentType) finalHeaders['Content-Type'] = contentType;
  } else if (body !== undefined) {
    payload = JSON.stringify(body);
    finalHeaders['Content-Type'] = 'application/json';
  }

  let response;
  try {
    response = await fetch(buildUrl(id, params, query), {
      method: op.method,
      headers: finalHeaders,
      body: payload,
      credentials: 'include',
      signal,
    });
  } catch (cause) {
    if (cause?.name === 'AbortError') throw cause;
    throw ApiError.network(cause);
  }

  if (response.ok) return unwrap(response);

  const error = await ApiError.fromResponse(response);
  if (error.status === 401 && error.code === 'TOKEN_EXPIRED' && retry && op.auth !== 'public') {
    try {
      await refreshAccess();
    } catch {
      window.dispatchEvent(new CustomEvent('auth:logout', { detail: { reason: 'REFRESH_FAILED' } }));
      throw error;
    }
    return call(id, { params, query, body, headers: { ...(headers ?? {}), 'Idempotency-Key': finalHeaders['Idempotency-Key'] }, signal, rawBody, contentType, retry: false });
  }
  if (error.status === 401 && (error.code.startsWith('PROFILE_') || error.code === 'MISSING_PROFILE_TOKEN')) {
    tokenStore.setProfile(null);
    window.dispatchEvent(new CustomEvent('profile:reselect', { detail: { code: error.code } }));
  } else if (error.status === 401 && ['TOKEN_INVALID', 'AUTH_REQUIRED'].includes(error.code) && op.auth !== 'public') {
    window.dispatchEvent(new CustomEvent('auth:logout', { detail: { reason: error.code } }));
  }
  throw error;
}

export const api = Object.freeze({
  call,
  url: buildUrl,
  operation,
  refresh: refreshAccess,
  /** Fire-and-forget POST that survives page unload (no auth header possible). */
  beacon(id, body) {
    const url = buildUrl(id);
    const blob = new Blob([JSON.stringify(body)], { type: 'application/json' });
    if (navigator.sendBeacon?.(url, blob)) return;
    fetch(url, { method: 'POST', body: blob, keepalive: true, headers: { 'Content-Type': 'application/json' } }).catch(
      () => {},
    );
  },
});
