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
  let manifestParsed = false;

  hls.on(Hls.Events.MANIFEST_PARSED, (_event, data) => {
    manifestParsed = true;
    if (maxHeight) {
      // DRM/plan ceiling: never select renditions above the entitlement.
      const allowed = data.levels.map((l, i) => ({ h: l.height, i })).filter((l) => !l.h || l.h <= maxHeight);
      if (allowed.length) hls.autoLevelCapping = Math.max(...allowed.map((l) => l.i));
    }
    onReady?.();
  });
  hls.on(Hls.Events.ERROR, (_event, data) => {
    if (!data.fatal) return;
    // Before the manifest arrives there is nothing to resume: startLoad() would be a silent no-op and
    // the viewer would watch a spinner forever. hls.js has already retried — report the real cause.
    if (data.type === Hls.ErrorTypes.NETWORK_ERROR && !manifestParsed) {
      onFatal?.(describeNetworkFailure(data));
      return;
    }
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
    onFatal?.(data.type === Hls.ErrorTypes.NETWORK_ERROR ? describeNetworkFailure(data) : { code: 'STREAM_FAILED', detail: data.details });
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

/**
 * Turn an hls.js network failure into the API's own error (our proxy answers with the JSON envelope:
 * `{ error: { code, details: { reason } } }`), so the viewer sees *why* — not a generic failure.
 */
export function describeNetworkFailure(data) {
  let body = null;
  try {
    body = JSON.parse(data.networkDetails?.responseText ?? data.response?.data ?? 'null');
  } catch {
    body = null; // not our JSON (CDN error page, aborted request …)
  }
  const status = data.response?.code ?? data.networkDetails?.status ?? 0;
  const code = body?.error?.code ?? (status === 403 ? 'SESSION_INACTIVE' : /timeout/i.test(data.details ?? '') ? 'STREAM_TIMEOUT' : 'STREAM_FAILED');
  const details = body?.error?.details ?? {};
  return { code, reason: details.reason ?? null, status: details.status ?? status, detail: data.details };
}
