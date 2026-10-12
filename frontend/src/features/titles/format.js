/** Display helpers shared by every titles view (one wording everywhere). */
const RATING_LABEL = { general: 'Genel izleyici', teen: '13+', adult: '18+', unrated: 'Derecelendirilmemiş' };
const RATING_SHORT = { general: 'G', teen: '13+', adult: '18+', unrated: 'NR' };

export const ratingLabel = (rating) => RATING_LABEL[rating] ?? rating;
export const ratingShort = (rating) => RATING_SHORT[rating] ?? rating;

export function duration(minutes) {
  if (!minutes) return null;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h} sa ${m ? `${m} dk` : ''}`.trim() : `${m} dk`;
}

/** "2012 · 12 dk" for movies, "2016 · 2 sezon" for series — only the parts that exist. */
export function factLine(card) {
  const length = card.kind === 'series' ? (card.season_count ? `${card.season_count} sezon` : null) : duration(card.runtime_minutes);
  return [card.year, length].filter(Boolean);
}
