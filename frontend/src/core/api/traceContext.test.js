import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from './client';
import { newTraceContext } from './traceContext';

const TRACEPARENT = /^00-([0-9a-f]{32})-([0-9a-f]{16})-00$/;

describe('W3C trace context', () => {
  it('mints a valid traceparent that leaves sampling to the server (flags 00)', () => {
    const { traceId, header } = newTraceContext();
    const [, id, parent] = TRACEPARENT.exec(header);
    expect(id).toBe(traceId);
    expect(id).not.toBe('0'.repeat(32));
    expect(parent).not.toBe('0'.repeat(16));
  });

  it('never repeats a trace id', () => {
    const ids = new Set(Array.from({ length: 500 }, () => newTraceContext().traceId));
    expect(ids.size).toBe(500);
  });
});

describe('API calls carry their trace', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('sends traceparent, and a failure reports the trace id it was sent with', async () => {
    let sent;
    vi.stubGlobal('fetch', vi.fn(async (_url, init) => {
      sent = init.headers.traceparent;
      return new Response(JSON.stringify({ success: false, error: { code: 'INVALID_CREDENTIALS', request_id: 'r1' } }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      });
    }));
    const error = await api.call('identity_login', { body: { username: 'a', password: 'b' } }).catch((e) => e);
    expect(sent).toMatch(TRACEPARENT);
    expect(error.code).toBe('INVALID_CREDENTIALS');
    expect(error.traceId).toBe(TRACEPARENT.exec(sent)[1]);
    expect(error.requestId).toBe('r1');
  });

  it('a network failure still knows its trace id', async () => {
    let sent;
    vi.stubGlobal('fetch', vi.fn(async (_url, init) => {
      sent = init.headers.traceparent;
      throw new TypeError('Failed to fetch');
    }));
    const error = await api.call('identity_login', { body: { username: 'a', password: 'b' } }).catch((e) => e);
    expect(error.code).toBe('NETWORK');
    expect(error.traceId).toBe(TRACEPARENT.exec(sent)[1]);
  });
});
