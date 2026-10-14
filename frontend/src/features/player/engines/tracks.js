/**
 * One track model for every engine, so the player menu lists and switches renditions without
 * knowing whether hls.js, Shaka or the browser itself is playing:
 *
 *   quality   [{ id, height, bitrate }]   best first; `qualityId` -1 = automatic (ABR)
 *   audio     [{ id, lang, name }]        `audioId` = the active one
 *   text      [{ id, lang, name }]        `textId` -1 = subtitles off
 *   playingHeight                         what ABR is showing right now ("Otomatik (720p)")
 *
 * Engines implement `tracks()` (a snapshot) and `select(kind, id)`, and call `onTracks()` whenever
 * the snapshot may have changed. An engine that cannot switch something just returns no options.
 */
export const NO_TRACKS = Object.freeze({ quality: [], qualityId: -1, playingHeight: null, audio: [], audioId: null, text: [], textId: -1 });

export const AUTO = -1;
export const OFF = -1;

/**
 * Renditions as a viewer sees them: one entry per height (the highest bitrate wins — two "720p"
 * entries mean nothing to a person), nothing above the plan's ceiling, best first.
 * @param {{ height?: number, bitrate?: number }[]} levels  engine-native list; `id` = index unless given
 */
export function qualityOptions(levels, maxHeight = null) {
  const best = new Map();
  levels.forEach((level, index) => {
    const height = level.height ?? 0;
    if (!height || (maxHeight && height > maxHeight)) return;
    const option = { id: level.id ?? index, height, bitrate: level.bitrate ?? 0 };
    const seen = best.get(height);
    if (!seen || option.bitrate > seen.bitrate) best.set(height, option);
  });
  return [...best.values()].sort((a, b) => b.height - a.height);
}

export function qualityLabel(height) {
  if (!height) return '';
  if (height >= 2160) return `${height}p 4K`;
  if (height >= 720) return `${height}p HD`;
  return `${height}p`;
}

const languageNames = new Map();
function languageName(code, locale) {
  try {
    if (!languageNames.has(locale)) languageNames.set(locale, new Intl.DisplayNames([locale], { type: 'language' }));
    const name = languageNames.get(locale).of(code);
    return name && name.toLowerCase() !== code.toLowerCase() ? name.charAt(0).toLocaleUpperCase(locale) + name.slice(1) : null;
  } catch {
    return null; // invalid / unknown tag
  }
}

/**
 * Language names in the viewer's language ("Türkçe", "İngilizce" / "Turkish", "English") and —
 * when two tracks share a language — "İngilizce (Commentary)". Falls back to the manifest's NAME,
 * then to `unnamed(n)` ("Parça 2").
 */
export function trackLabels(tracks, { locale = 'tr', unnamed = (n) => `#${n}` } = {}) {
  const base = tracks.map((t) => (t.lang && languageName(t.lang, locale)) || t.name || null);
  return tracks.map((t, i) => {
    if (!base[i]) return unnamed(i + 1);
    const clash = base.some((b, j) => j !== i && b === base[i]);
    return clash && t.name && t.name !== base[i] ? `${base[i]} (${t.name})` : base[i];
  });
}

/** Same language? ("en" matches "en-US"; the base subtag decides.) */
export function sameLanguage(a, b) {
  if (!a || !b) return false;
  return a.toLowerCase().split('-')[0] === b.toLowerCase().split('-')[0];
}
