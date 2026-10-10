/** Native playback: Safari/iOS HLS and progressive files. Listener-leak free (FE-07). */
export function createNativeEngine(video, { onFatal, onReady }) {
  const ready = () => onReady?.();
  const failed = () => onFatal?.({ code: 'STREAM_FAILED', detail: video.error?.message });
  video.addEventListener('loadedmetadata', ready);
  video.addEventListener('error', failed);
  return {
    id: 'native',
    load(url) {
      video.src = url;
      video.load();
    },
    stats: () => ({ bitrateKbps: null, resolution: video.videoHeight ? `${video.videoHeight}p` : null }),
    destroy() {
      video.removeEventListener('loadedmetadata', ready);
      video.removeEventListener('error', failed);
      video.removeAttribute('src');
      video.load();
    },
  };
}
