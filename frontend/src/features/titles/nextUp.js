/**
 * What the primary button of a detail page should play.
 *
 * Movie: its source — "resume" if started and not finished.
 * Series (Netflix rule): the most recently watched unfinished episode; else the episode after the
 * most recently finished one; else the first available episode.
 *
 * @param {object} detail  TitleDetailOut
 * @param {Map<string, {completed: boolean, updated_at: string|null, position_s: number, duration_s: number}>} progress
 * @param {(key: string, params?: object) => string} t  titles translator (labels)
 * @returns {{ ref: string, label: string, resume: boolean, episode?: object, season?: number } | null}
 */
export function nextUp(detail, progress, t) {
  if (detail.card.kind === 'movie') {
    if (!detail.card.available || !detail.play_ref) return null;
    const p = progress.get(detail.play_ref);
    const resume = Boolean(p && !p.completed);
    return { ref: detail.play_ref, label: t(resume ? 'resume' : 'play'), resume };
  }

  const episodes = detail.seasons.flatMap((s) => s.episodes.map((e) => ({ ...e, season: s.number })));
  const playable = episodes.filter((e) => e.available && e.play_ref);
  if (!playable.length) return null;

  const watched = playable
    .map((e) => ({ e, p: progress.get(e.play_ref) }))
    .filter(({ p }) => p?.updated_at)
    .sort((a, b) => b.p.updated_at.localeCompare(a.p.updated_at));

  const pick = (e, resume) => ({
    ref: e.play_ref,
    label: t('playEpisode', { action: t(resume ? 'resume' : 'play'), code: t('episodeCode', { season: e.season, episode: e.number }) }),
    resume,
    episode: e,
    season: e.season,
  });

  const latest = watched[0];
  if (latest && !latest.p.completed) return pick(latest.e, true);
  if (latest) {
    const after = playable.find((e) => episodes.indexOf(e) > episodes.indexOf(latest.e));
    if (after) return pick(after, false);
  }
  return pick(playable[0], false);
}

/** "12 dk kaldı" for a started item, or null. */
export function remaining(p, t) {
  if (!p || p.completed || !p.duration_s) return null;
  const left = Math.max(1, Math.round((p.duration_s - p.position_s) / 60));
  return t('left', { minutes: left });
}
