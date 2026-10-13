import { describe, expect, it } from 'vitest';
import { describeNetworkFailure } from './hlsJsEngine';

const xhr = (status, body) => ({ details: 'manifestLoadError', response: { code: status }, networkDetails: { status, responseText: body } });

describe('describeNetworkFailure', () => {
  it('surfaces the proxy error code and reason (why, not where)', () => {
    const body = JSON.stringify({ error: { code: 'UPSTREAM_UNAVAILABLE', details: { reason: 'tls' } } });
    expect(describeNetworkFailure(xhr(502, body))).toMatchObject({ code: 'UPSTREAM_UNAVAILABLE', reason: 'tls' });
  });

  it('reports the upstream HTTP status, not the proxy status', () => {
    const body = JSON.stringify({ error: { code: 'UPSTREAM_STATUS', details: { status: 404 } } });
    expect(describeNetworkFailure(xhr(502, body))).toMatchObject({ code: 'UPSTREAM_STATUS', status: 404 });
  });

  it('falls back sensibly for non-JSON answers and timeouts', () => {
    expect(describeNetworkFailure(xhr(403, '<html>'))).toMatchObject({ code: 'SESSION_INACTIVE' });
    expect(describeNetworkFailure({ details: 'manifestLoadTimeOut', networkDetails: {} })).toMatchObject({ code: 'STREAM_TIMEOUT' });
    expect(describeNetworkFailure(xhr(500, ''))).toMatchObject({ code: 'STREAM_FAILED' });
  });
});
