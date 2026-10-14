import Hls from 'hls.js';
import { AUTO, OFF, qualityOptions } from './tracks';

/**
 * hls.js engine. No credentials are ever attached (FE-03): every playlist,
 * segment and AES-128 key URI is a signed, session-bound URL minted by the
 * backend, so cross-origin CDNs never see an Authorization header.
 */
export function createHlsJsEngine(video, { isLive, onFatal, onReady, onTracks, maxHeight }) {
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
    onTracks?.();
  });
  for (const event of [
    Hls.Events.LEVEL_SWITCHED,
    Hls.Events.AUDIO_TRACKS_UPDATED,
    Hls.Events.AUDIO_TRACK_SWITCHED,
    Hls.Events.SUBTITLE_TRACKS_UPDATED,
    Hls.Events.SUBTITLE_TRACK_SWITCH,
  ]) {
    hls.on(event, () => onTracks?.());
  }
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
  // Remember which MediaSource URL is ours: teardown must never clear a <video> another engine owns
  // (an overlapping mount/unmount — React StrictMode — once wiped the live engine's media this way).
  let ownedSrc = null;
  hls.on(Hls.Events.MEDIA_ATTACHED, () => {
    ownedSrc = video.currentSrc || video.src || null;
  });
  hls.attachMedia(video);

  return {
    id: 'hlsjs',
    load: (url) => hls.loadSource(url),
    stats: () => {
      const level = hls.levels?.[hls.currentLevel];
      return { bitrateKbps: level ? Math.round(level.bitrate / 1000) : null, resolution: level?.height ? `${level.height}p` : null };
    },
    tracks: () => ({
      // hls.js addresses levels and tracks by *array index* (its `id` fields are manifest ids): use indexes.
      quality: qualityOptions((hls.levels ?? []).map((l, id) => ({ id, height: l.height, bitrate: l.bitrate })), maxHeight),
      qualityId: hls.autoLevelEnabled ? AUTO : hls.manualLevel,
      playingHeight: hls.levels?.[hls.currentLevel]?.height ?? null,
      audio: (hls.audioTracks ?? []).map((t, id) => ({ id, lang: t.lang ?? null, name: t.name ?? null })),
      audioId: hls.audioTrack,
      text: (hls.subtitleTracks ?? []).map((t, id) => ({ id, lang: t.lang ?? null, name: t.name ?? null })),
      textId: hls.subtitleDisplay ? hls.subtitleTrack : OFF,
    }),
    select(kind, id) {
      if (kind === 'quality') {
        // nextLevel: switch at the next fragment — no buffer flush, no stall. -1 hands control back to ABR.
        hls.nextLevel = id;
      } else if (kind === 'audio') {
        hls.audioTrack = id;
      } else if (kind === 'text') {
        if (id !== OFF) hls.subtitleDisplay = true;
        hls.subtitleTrack = id; // -1 also stops downloading the subtitle playlist
      }
      onTracks?.();
    },
    destroy() {
      const stillOurs = ownedSrc !== null && (video.currentSrc || video.src) === ownedSrc;
      hls.destroy();
      if (stillOurs) {
        video.removeAttribute('src');
        video.load();
      }
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
