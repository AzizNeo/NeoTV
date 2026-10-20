import { afterEach, describe, expect, it, vi } from 'vitest';
import { api, isTransient, retryDelayMs } from './client';
import { tokenStore } from '@/core/auth/tokenStore';

const json = (status, body, headers = {}) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } });
const ok = () => json(200, { success: true, data: { access_token: 'fresh', token_type: 'Bearer' } });
const failed = (status, code, details) => json(status, { success: false, error: { code, message: code, details } });

describe('session restore (refresh) under passing problems', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    tokenStore.clear();
  });

  it('waits out a rate limit (the server says how long) and restores the session', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(failed(429, 'RATE_LIMITED', { retry_after_seconds: 0.01 }))
      .mockResolvedValueOnce(ok());
    vi.stubGlobal('fetch', fetch);
    await expect(api.refresh()).resolves.toMatchObject({ access_token: 'fresh' });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(tokenStore.getAccess()).toBe('fresh');
  });

  it('retries a dropped connection or an outage, then gives up with the last error', async () => {
    vi.useFakeTimers();
    const fetch = vi.fn()
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
      .mockResolvedValueOnce(failed(503, 'TEMPORARILY_UNAVAILABLE'))
      .mockResolvedValueOnce(failed(502, 'HTTP_502'));
    vi.stubGlobal('fetch', fetch);
    const restore = api.refresh().catch((error) => error);
    await vi.runAllTimersAsync();
    const error = await restore;
    vi.useRealTimers();
    expect(fetch).toHaveBeenCalledTimes(3);
    expect(error.status).toBe(502);
  });

  it('takes an answer about the session itself as final: no retry', async () => {
    const fetch = vi.fn().mockResolvedValue(failed(401, 'REFRESH_INVALID'));
    vi.stubGlobal('fetch', fetch);
    await expect(api.refresh()).rejects.toMatchObject({ status: 401, code: 'REFRESH_INVALID' });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('classifies and paces retries', () => {
    expect([0, 429, 500, 503].map((status) => isTransient({ status }))).toEqual([true, true, true, true]);
    expect([400, 401, 403].map((status) => isTransient({ status }))).toEqual([false, false, false]);
    expect(retryDelayMs({ details: { retry_after_seconds: 2 } }, 0)).toBe(2000);
    expect(retryDelayMs({ details: { retry_after_seconds: 600 } }, 0)).toBe(10_000); // capped
    expect([0, 1].map((attempt) => retryDelayMs({}, attempt))).toEqual([500, 1000]);
  });
});
