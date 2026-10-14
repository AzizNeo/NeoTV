/**
 * Browse filters ⇄ URL search params. The URL is the single source of truth: shareable links,
 * working Back button, and defaults are omitted so URLs stay short.
 */
// `label`: [message key, params] in the titles catalog — words are the view's business.
export const KINDS = [
  { id: '', label: ['browse.kinds.all'] },
  { id: 'movie', label: ['browse.kinds.movie'] },
  { id: 'series', label: ['browse.kinds.series'] },
];
export const SORTS = [
  { id: 'recent', label: ['browse.sorts.recent'] },
  { id: 'year', label: ['browse.sorts.year'] },
  { id: 'name', label: ['browse.sorts.name'] },
];
export const DECADES = [
  { id: '', label: ['browse.decades.all'] },
  { id: '2020', label: ['browse.decades.ler', { decade: '2020' }], from: 2020, to: 2029 },
  { id: '2010', label: ['browse.decades.lar', { decade: '2010' }], from: 2010, to: 2019 },
  { id: '2000', label: ['browse.decades.ler', { decade: '2000' }], from: 2000, to: 2009 },
  { id: '1990', label: ['browse.decades.lar', { decade: '1990' }], from: 1990, to: 1999 },
  { id: 'older', label: ['browse.decades.older'], from: 1888, to: 1989 },
];
const DEFAULTS = { q: '', genre: '', kind: '', sort: 'recent', decade: '' };
const valid = { kind: new Set(KINDS.map((k) => k.id)), sort: new Set(SORTS.map((s) => s.id)), decade: new Set(DECADES.map((d) => d.id)) };

/** URLSearchParams → filters (unknown values fall back to defaults instead of breaking the page). */
export function readFilters(params) {
  const pick = (key) => {
    const value = (params.get(key) ?? DEFAULTS[key]).trim();
    return valid[key] && !valid[key].has(value) ? DEFAULTS[key] : value;
  };
  return { q: pick('q').slice(0, 100), genre: pick('genre').slice(0, 80), kind: pick('kind'), sort: pick('sort'), decade: pick('decade') };
}

/** Filters → URLSearchParams with defaults omitted (stable, short, shareable). */
export function writeFilters(filters) {
  const params = new URLSearchParams();
  for (const [key, fallback] of Object.entries(DEFAULTS)) {
    const value = (filters[key] ?? fallback).toString().trim();
    if (value && value !== fallback) params.set(key, value);
  }
  return params;
}

/** Filters → titles_browse query (API names). */
export function toApiQuery(filters, perPage) {
  const decade = DECADES.find((d) => d.id === filters.decade);
  return {
    search: filters.q.length >= 2 ? filters.q : undefined,
    genre: filters.genre || undefined,
    kind: filters.kind || undefined,
    sort: filters.sort,
    year_from: decade?.from,
    year_to: decade?.to,
    per_page: perPage,
  };
}

export const isFiltered = (f) => Boolean(f.q || f.genre || f.kind || f.decade || f.sort !== DEFAULTS.sort);
