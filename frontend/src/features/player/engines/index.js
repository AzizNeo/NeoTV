/**
 * Player engine selection — adding a playback technology is adding an entry
 * here; the UI never changes.
 *
 *   EME DRM (license URLs present)  → shaka (lazy chunk)
 *   HLS + MediaSource                → hls.js (lazy chunk; AES-128 keys handled natively)
 *   HLS on Safari/iOS, MP4 …         → native <video>
 *
 * The player libraries are loaded when a stream opens, never with the app: this module is imported
 * by the always-mounted PlayerProvider, so a static import here would ship hls.js (~600 kB) to every
 * page, the sign-in page included. That is why `canPlay` may be async — hls.js answers "supported?"
 * itself, after its chunk loads, instead of a copy of its checks drifting here.
 *
 * Every engine returns { id, load(url), stats(), tracks(), select(kind, id), destroy() } and reports
 * through the callbacks { onReady, onFatal, onTracks } — the track model lives in ./tracks.js.
 */
import { createNativeEngine } from './nativeEngine';

const hlsJs = () => import('./hlsJsEngine');

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
  { id: 'hlsjs', canPlay: async (s) => s.isHls && (await hlsJs()).hlsJsSupported(), load: () => hlsJs().then((m) => m.createHlsJsEngine) },
  {
    id: 'native',
    canPlay: (s, video) => video.canPlayType(s.isHls ? 'application/vnd.apple.mpegurl' : 'video/mp4') !== '',
    load: async () => createNativeEngine,
  },
];

/** The first engine that can play the source, in order (some answer only after their chunk loads). */
async function pickEngine(source, video) {
  for (const entry of ENGINES) {
    if (await entry.canPlay(source, video)) return entry;
  }
  return null;
}

export async function createEngine(video, source, callbacks) {
  const entry = await pickEngine(source, video);
  if (!entry) {
    throw new UnsupportedPlaybackError(`No engine for drm=${Boolean(source.drm)} hls=${source.isHls}`);
  }
  const factory = await entry.load();
  return factory(video, { ...callbacks, isLive: source.isLive, drm: source.drm, maxHeight: source.maxHeight });
}
