/** Pure helpers of the TMDB admin section (kept out of the component so they are unit-testable). */

// Mirrors app/modules/titles/domain.py: Turkish letters first, then strip accents.
const TRANSLIT = { ç: 'c', ğ: 'g', ı: 'i', İ: 'i', ö: 'o', ş: 's', ü: 'u', Ç: 'c', Ğ: 'g', Ö: 'o', Ş: 's', Ü: 'u' };
const SLUG_MAX = 80;

/** `"Çılgın Şehir 2"` → `"cilgin-sehir-2"` — the same slug the backend would derive. */
export function slugify(text) {
  const ascii = [...(text ?? '')].map((ch) => TRANSLIT[ch] ?? ch).join('').normalize('NFKD').replace(/[̀-ͯ]/g, '');
  return ascii.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, SLUG_MAX).replace(/-+$/, '');
}

/** The public TMDB page of a hit or a link (`kind` is the platform's: movie | series). */
export const tmdbPage = ({ kind, tmdb_id: id }) => `https://www.themoviedb.org/${kind === 'series' ? 'tv' : 'movie'}/${id}`;
