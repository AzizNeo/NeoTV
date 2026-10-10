/**
 * Player engine selection — adding a playback technology is adding an entry
 * here; the UI never changes.
 *
 *   EME DRM (license URLs present)  → shaka (lazy chunk)
 *   HLS + MediaSource                → hls.js (AES-128 keys handled natively)
 *   HLS on Safari/iOS, MP4 …         → native <video>
 */
import { createHlsJsEngine, hlsJsSupported } from './hlsJsEngine';
import { createNativeEngine } from './nativeEngine';

export class UnsupportedPlaybackError extends Error {
  name = 'UnsupportedPlaybackError';
  code = 'UNSUPPORTED_PLAYBACK';
}

const RESOLUTION_HEIGHT = { '240p': 240, '360p': 360, '480p': 480, '720p': 720, '1080p': 1080, '1440p': 1440, '2160p': 2160 };

export function describeSource(session) {
  const drm = session.drm ?? null;
  const isHls = /mpegurl/i.test(session.mime_type) || /\.m3u8(\?|$)/i.test(session.manifest_url);
  const emeSystems = (drm?.systems ?? '').split(',').filter((s) => s && s !== 'aes-128');
  return {
    url: session.manifest_url,
    isHls,
    isLive: session.is_live,
    drm,
    needsEme: emeSystems.length > 0 && !(drm?.systems ?? '').split(',').includes('aes-128'),
    maxHeight: RESOLUTION_HEIGHT[drm?.max_resolution] ?? null,
  };
}

const ENGINES = [
  { id: 'shaka', canPlay: (s) => s.needsEme, load: () => import('./shakaEngine').then((m) => m.createShakaEngine) },
  { id: 'hlsjs', canPlay: (s) => s.isHls && hlsJsSupported(), load: async () => createHlsJsEngine },
  {
    id: 'native',
    canPlay: (s, video) => video.canPlayType(s.isHls ? 'application/vnd.apple.mpegurl' : 'video/mp4') !== '',
    load: async () => createNativeEngine,
  },
];

export async function createEngine(video, source, callbacks) {
  const entry = ENGINES.find((e) => e.canPlay(source, video));
  if (!entry) {
    throw new UnsupportedPlaybackError(`No engine for drm=${Boolean(source.drm)} hls=${source.isHls}`);
  }
  const factory = await entry.load();
  return factory(video, { ...callbacks, isLive: source.isLive, drm: source.drm, maxHeight: source.maxHeight });
}
