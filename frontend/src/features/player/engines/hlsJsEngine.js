import Hls from 'hls.js';

/**
 * hls.js engine. No credentials are ever attached (FE-03): every playlist,
 * segment and AES-128 key URI is a signed, session-bound URL minted by the
 * backend, so cross-origin CDNs never see an Authorization header.
 */
export function createHlsJsEngine(video, { isLive, onFatal, onReady, maxHeight }) {
  const hls = new Hls({
    enableWorker: true,
    lowLatencyMode: isLive,
    maxBufferLength: 30,
    maxMaxBufferLength: 60,
    capLevelToPlayerSize: true,
    abrEwmaDefaultEstimate: 500_000,
  });
  let networkRetries = 0;
  let mediaRecoveries = 0;

  hls.on(Hls.Events.MANIFEST_PARSED, (_event, data) => {
    if (maxHeight) {
      // DRM/plan ceiling: never select renditions above the entitlement.
      const allowed = data.levels.map((l, i) => ({ h: l.height, i })).filter((l) => !l.h || l.h <= maxHeight);
      if (allowed.length) hls.autoLevelCapping = Math.max(...allowed.map((l) => l.i));
    }
    onReady?.();
  });
  hls.on(Hls.Events.ERROR, (_event, data) => {
    if (!data.fatal) return;
    if (data.type === Hls.ErrorTypes.NETWORK_ERROR && networkRetries < 3) {
      networkRetries += 1;
      hls.startLoad();
      return;
    }
    if (data.type === Hls.ErrorTypes.MEDIA_ERROR && mediaRecoveries < 2) {
      mediaRecoveries += 1;
      hls.recoverMediaError();
      return;
    }
    onFatal?.({ code: data.response?.code === 403 ? 'SESSION_INACTIVE' : 'STREAM_FAILED', detail: data.details });
  });
  hls.attachMedia(video);

  return {
    id: 'hlsjs',
    load: (url) => hls.loadSource(url),
    stats: () => {
      const level = hls.levels?.[hls.currentLevel];
      return { bitrateKbps: level ? Math.round(level.bitrate / 1000) : null, resolution: level?.height ? `${level.height}p` : null };
    },
    destroy() {
      hls.destroy();
      video.removeAttribute('src');
      video.load();
    },
  };
}

export const hlsJsSupported = () => Hls.isSupported();
