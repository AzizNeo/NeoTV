import { describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { usePlaybackSession } from './usePlaybackSession';

const call = vi.fn();
vi.mock('@/core/api/client', () => ({ api: { call: (...args) => call(...args), beacon: vi.fn() } }));

const at = (minutes) => new Date(Date.parse('2026-10-20T18:10:00Z') + minutes * 60_000).toISOString();

describe('the playback session', () => {
  it('opens an archive window when the item carries one', async () => {
    call.mockResolvedValue({ session_token: 't', heartbeat_interval_s: 10, manifest_url: '/x' });
    const archiveWindow = { start: at(-70), end: at(-10) };
    const { unmount } = renderHook(() => usePlaybackSession('live:1', archiveWindow));
    await waitFor(() => expect(call).toHaveBeenCalledWith('playback_open_session', expect.objectContaining({ body: { content_ref: 'live:1', window: archiveWindow } })));
    unmount();
  });
});
