import { beforeEach, describe, expect, it, vi } from 'vitest';

// If engines/index.js imported hls.js statically, loading it would evaluate this factory and throw:
// the always-mounted PlayerProvider imports it, so that would put hls.js on every page again.
vi.mock('hls.js', () => {
  throw new Error('hls.js was loaded eagerly');
});

const hls = { supported: true, created: vi.fn(() => ({ id: 'hlsjs' })) };
vi.mock('./hlsJsEngine', () => ({
  hlsJsSupported: () => hls.supported,
  createHlsJsEngine: (...args) => hls.created(...args),
}));
vi.mock('./shakaEngine', () => ({ createShakaEngine: () => ({ id: 'shaka' }) }));
vi.mock('./nativeEngine', () => ({ createNativeEngine: () => ({ id: 'native' }) }));

const { createEngine, describeSource, UnsupportedPlaybackError } = await import('./index');

const video = (canPlay = '') => ({ canPlayType: () => canPlay });
const hlsSession = { manifest_url: 'https://cdn/x/master.m3u8?sig=1', mime_type: 'application/vnd.apple.mpegurl', is_live: false };

describe('engine selection', () => {
  beforeEach(() => {
    hls.supported = true;
    hls.created.mockClear();
  });

  it('loads without hls.js — the library arrives only when a stream opens', () => {
    expect(describeSource(hlsSession).isHls).toBe(true);
  });

  it('plays HLS with hls.js where MediaSource allows it', async () => {
    expect((await createEngine(video(), describeSource(hlsSession), {})).id).toBe('hlsjs');
    expect(hls.created).toHaveBeenCalledOnce();
  });

  it('falls back to the native player when hls.js cannot run (Safari/iOS without MSE)', async () => {
    hls.supported = false;
    expect((await createEngine(video('maybe'), describeSource(hlsSession), {})).id).toBe('native');
  });

  it('uses shaka for EME DRM', async () => {
    const drm = { ...hlsSession, drm: { systems: 'widevine', license_url: 'https://lic' } };
    expect((await createEngine(video(), describeSource(drm), {})).id).toBe('shaka');
  });

  it('names the failure when nothing can play the source', async () => {
    hls.supported = false;
    await expect(createEngine(video(''), describeSource(hlsSession), {})).rejects.toBeInstanceOf(UnsupportedPlaybackError);
  });
});
