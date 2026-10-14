/**
 * Display helpers shared by every titles view (one wording everywhere). `t` is the titles
 * translator (useT() in components, translate(...) in tests).
 */
const RATING_SHORT = { general: 'G', teen: '13+', adult: '18+', unrated: 'NR' };

export const ratingLabel = (rating, t) => (rating in RATING_SHORT ? t(`ratings.${rating}`) : rating);
export const ratingShort = (rating) => RATING_SHORT[rating] ?? rating;

export function duration(minutes, t) {
  if (!minutes) return null;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return t('facts.minutes', { m });
  return m ? t('facts.hoursMinutes', { h, m }) : t('facts.hours', { h });
}

/** "2012 · 12 dk" for movies, "2016 · 2 sezon" for series — only the parts that exist. */
export function factLine(card, t) {
  const length = card.kind === 'series' ? (card.season_count ? t('facts.seasons', { count: card.season_count }) : null) : duration(card.runtime_minutes, t);
  return [card.year, length].filter(Boolean);
}

/** "S1 B2" / "S1 E2". */
export const episodeCode = (season, episode, t) => t('episodeCode', { season, episode });
