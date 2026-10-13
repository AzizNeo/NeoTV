/** Native playback: Safari/iOS HLS and progressive files. Listener-leak free (FE-07). */
export function createNativeEngine(video, { onFatal, onReady }) {
  const ready = () => onReady?.();
  const failed = () => onFatal?.({ code: 'STREAM_FAILED', detail: video.error?.message });
  let ownedSrc = null;
  video.addEventListener('loadedmetadata', ready);
  video.addEventListener('error', failed);
  return {
    id: 'native',
    load(url) {
      video.src = url;
      ownedSrc = video.src; // normalised absolute URL, as the element reports it
      video.load();
    },
    stats: () => ({ bitrateKbps: null, resolution: video.videoHeight ? `${video.videoHeight}p` : null }),
    destroy() {
      video.removeEventListener('loadedmetadata', ready);
      video.removeEventListener('error', failed);
      if (ownedSrc && video.src === ownedSrc) {
        // only our own source: never tear down a <video> another engine has taken over
        video.removeAttribute('src');
        video.load();
      }
    },
  };
}
