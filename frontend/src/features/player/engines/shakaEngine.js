/**
 * Shaka engine — EME DRM (ClearKey today; Widevine/PlayReady/FairPlay as soon
 * as the backend installs an issuer, with no frontend change: the license
 * URLs arrive in `source.drm` as `<system>.license_url`).
 * Loaded lazily: users without DRM content never download it.
 */
import shaka from 'shaka-player';

const KEY_SYSTEMS = {
  clearkey: 'org.w3.clearkey',
  widevine: 'com.widevine.alpha',
  playready: 'com.microsoft.playready',
  fairplay: 'com.apple.fps',
};

export function createShakaEngine(video, { onFatal, onReady, drm, maxHeight }) {
  shaka.polyfill.installAll();
  const player = new shaka.Player();
  const servers = {};
  for (const system of (drm?.systems ?? '').split(',').filter(Boolean)) {
    const url = drm[`${system}.license_url`];
    if (url && KEY_SYSTEMS[system]) servers[KEY_SYSTEMS[system]] = url;
  }
  player.configure({
    drm: { servers },
    abr: { restrictions: maxHeight ? { maxHeight } : {} },
    streaming: { retryParameters: { maxAttempts: 3 } },
  });
  player.addEventListener('error', (event) => onFatal?.({ code: 'STREAM_FAILED', detail: event.detail?.code }));

  return {
    id: 'shaka',
    async load(url) {
      try {
        await player.attach(video);
        await player.load(url);
        onReady?.();
      } catch (error) {
        onFatal?.({ code: error?.code === 6007 ? 'DRM_LICENSE_FAILED' : 'STREAM_FAILED', detail: error?.code });
      }
    },
    stats: () => {
      const s = player.getStats?.();
      return { bitrateKbps: s?.streamBandwidth ? Math.round(s.streamBandwidth / 1000) : null, resolution: s?.height ? `${s.height}p` : null };
    },
    destroy() {
      player.destroy();
    },
  };
}
