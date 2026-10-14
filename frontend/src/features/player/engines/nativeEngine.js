import { OFF } from './tracks';

const isSubtitle = (t) => t.kind === 'subtitles' || t.kind === 'captions';

/**
 * Native playback: Safari/iOS HLS and progressive files. Listener-leak free (FE-07).
 * Tracks: the browser exposes subtitles (`textTracks`) and — Safari only — audio (`audioTracks`).
 * Quality stays automatic: native HLS has no rendition switching API.
 */
export function createNativeEngine(video, { onFatal, onReady, onTracks }) {
  const ready = () => onReady?.();
  const failed = () => onFatal?.({ code: 'STREAM_FAILED', detail: video.error?.message });
  const changed = () => onTracks?.();
  const lists = [video.textTracks, video.audioTracks].filter(Boolean);
  let ownedSrc = null;
  video.addEventListener('loadedmetadata', ready);
  video.addEventListener('error', failed);
  video.addEventListener('resize', changed);
  for (const list of lists) {
    list.addEventListener('addtrack', changed);
    list.addEventListener('removetrack', changed);
    list.addEventListener('change', changed);
  }
  const subtitles = () => [...(video.textTracks ?? [])].filter(isSubtitle);
  const audios = () => [...(video.audioTracks ?? [])];

  return {
    id: 'native',
    load(url) {
      video.src = url;
      ownedSrc = video.src; // normalised absolute URL, as the element reports it
      video.load();
    },
    stats: () => ({ bitrateKbps: null, resolution: video.videoHeight ? `${video.videoHeight}p` : null }),
    tracks() {
      const text = subtitles();
      const audio = audios();
      return {
        quality: [],
        qualityId: -1,
        playingHeight: video.videoHeight || null,
        audio: audio.map((t, id) => ({ id, lang: t.language || null, name: t.label || null })),
        audioId: Math.max(0, audio.findIndex((t) => t.enabled)),
        text: text.map((t, id) => ({ id, lang: t.language || null, name: t.label || null })),
        textId: text.findIndex((t) => t.mode === 'showing'),
      };
    },
    select(kind, id) {
      if (kind === 'text') subtitles().forEach((t, i) => (t.mode = i === id && id !== OFF ? 'showing' : 'disabled'));
      if (kind === 'audio') audios().forEach((t, i) => (t.enabled = i === id));
      changed();
    },
    destroy() {
      video.removeEventListener('loadedmetadata', ready);
      video.removeEventListener('error', failed);
      video.removeEventListener('resize', changed);
      for (const list of lists) {
        list.removeEventListener('addtrack', changed);
        list.removeEventListener('removetrack', changed);
        list.removeEventListener('change', changed);
      }
      if (ownedSrc && video.src === ownedSrc) {
        // only our own source: never tear down a <video> another engine has taken over
        video.removeAttribute('src');
        video.load();
      }
    },
  };
}
