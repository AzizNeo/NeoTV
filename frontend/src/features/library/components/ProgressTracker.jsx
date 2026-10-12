/**
 * Contributed to `player.observers`: restores the resume position and saves
 * progress while a VOD plays (every 15 s, on pause and on close). Live content
 * is ignored. The player knows nothing about it.
 */
import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '@/core/api/client';
import { libraryKeys } from '../api';

const SAVE_EVERY_MS = 15_000;
const RESUME_MIN_S = 10;

export function ProgressTracker({ video, contentRef, isLive }) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!video || isLive) return undefined;
    let lastSaved = 0;
    let disposed = false;

    const save = () => {
      const duration = Number.isFinite(video.duration) ? Math.floor(video.duration) : 0;
      const position = Math.floor(video.currentTime);
      if (position < 5 || position === lastSaved) return;
      lastSaved = position;
      api
        .call('library_save_progress', { params: { content_ref: contentRef }, body: { position_s: position, duration_s: duration } })
        .catch(() => {}); // progress is best effort
    };

    api
      .call('library_get_progress', { params: { content_ref: contentRef } })
      .then((p) => {
        if (disposed || !p.has_progress || p.completed || p.position_s < RESUME_MIN_S) return;
        const seek = () => {
          video.currentTime = p.position_s;
        };
        if (video.readyState >= 1) seek();
        else video.addEventListener('loadedmetadata', seek, { once: true });
      })
      .catch(() => {});

    const timer = setInterval(() => !video.paused && save(), SAVE_EVERY_MS);
    video.addEventListener('pause', save);
    return () => {
      disposed = true;
      clearInterval(timer);
      video.removeEventListener('pause', save);
      save();
      queryClient.invalidateQueries({ queryKey: libraryKeys.continue });
      queryClient.invalidateQueries({ queryKey: libraryKeys.history });
      queryClient.invalidateQueries({ queryKey: libraryKeys.progress });
    };
  }, [video, contentRef, isLive, queryClient]);

  return null;
}
