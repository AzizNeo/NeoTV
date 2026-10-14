/**
 * Shaka engine — EME DRM (ClearKey today; Widevine/PlayReady/FairPlay as soon
 * as the backend installs an issuer, with no frontend change: the license
 * URLs arrive in `source.drm` as `<system>.license_url`).
 * Loaded lazily: users without DRM content never download it.
 */
import shaka from 'shaka-player';
import { AUTO, OFF, qualityOptions } from './tracks';

const KEY_SYSTEMS = {
  clearkey: 'org.w3.clearkey',
  widevine: 'com.widevine.alpha',
  playready: 'com.microsoft.playready',
  fairplay: 'com.apple.fps',
};

export function createShakaEngine(video, { onFatal, onReady, onTracks, drm, maxHeight }) {
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
  for (const event of ['trackschanged', 'variantchanged', 'adaptation', 'textchanged', 'texttrackvisibility']) {
    player.addEventListener(event, () => onTracks?.());
  }
  let manualQuality = AUTO;

  // Shaka thinks in variants (video × audio). Audio = the distinct languages/roles; quality = the
  // heights available *for the active audio*, so picking 720p never silently switches language.
  const variants = () => player.getVariantTracks();
  const activeVariant = () => variants().find((t) => t.active) ?? null;
  const audioChoices = () => player.getAudioLanguagesAndRoles();
  const textChoices = () => player.getTextTracks();

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
    tracks() {
      const active = activeVariant();
      const sameAudio = variants().filter((t) => !active || (t.language === active.language && t.roles.join() === active.roles.join()));
      const audio = audioChoices();
      const text = textChoices();
      return {
        quality: qualityOptions(sameAudio.map((t) => ({ id: t.id, height: t.height, bitrate: t.bandwidth })), maxHeight),
        qualityId: manualQuality,
        playingHeight: active?.height ?? null,
        audio: audio.map((a, id) => ({ id, lang: a.language || null, name: a.label || a.role || null })),
        audioId: Math.max(0, audio.findIndex((a) => a.language === active?.language && (!a.role || active?.roles.includes(a.role)))),
        text: text.map((t) => ({ id: t.id, lang: t.language || null, name: t.label || null })),
        textId: player.isTextTrackVisible() ? (text.find((t) => t.active)?.id ?? OFF) : OFF,
      };
    },
    select(kind, id) {
      if (kind === 'quality') {
        manualQuality = id;
        player.configure({ abr: { enabled: id === AUTO } });
        const track = variants().find((t) => t.id === id);
        if (track) player.selectVariantTrack(track, /* clearBuffer */ true);
      } else if (kind === 'audio') {
        const choice = audioChoices()[id];
        if (choice) player.selectAudioLanguage(choice.language, choice.role || undefined);
      } else if (kind === 'text') {
        const track = textChoices().find((t) => t.id === id);
        if (track) player.selectTextTrack(track);
        player.setTextTrackVisibility(id !== OFF);
      }
      onTracks?.();
    },
    destroy() {
      player.destroy();
    },
  };
}
