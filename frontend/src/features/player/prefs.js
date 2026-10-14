/**
 * Viewer choices the player remembers on this device (Netflix keeps your subtitle language and
 * volume between episodes and visits): `{ volume, muted, textLang, audioLang }`.
 * `textLang` is a BCP-47 tag, or 'off' once the viewer turned subtitles off on purpose.
 * Browser storage may be missing or throw (private mode, blocked site data): then nothing is remembered.
 */
import { OFF, sameLanguage } from './engines/tracks';

const KEY = 'neotv:player-prefs';

export function readPrefs() {
  try {
    const value = JSON.parse(window.localStorage.getItem(KEY) ?? '{}');
    return value && typeof value === 'object' ? value : {};
  } catch {
    return {};
  }
}

export function writePrefs(patch) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify({ ...readPrefs(), ...patch }));
  } catch {
    /* storage unavailable: the choice lasts for this session only */
  }
}

/**
 * Apply the remembered languages once per kind, the first time a source lists tracks of that kind
 * (`applied` is a per-source scratch object). Returns nothing; the engine reports the new state.
 */
export function applyPreferences(engine, snapshot, prefs, applied) {
  if (!applied.text && snapshot.text.length) {
    applied.text = true;
    if (prefs.textLang === 'off') {
      if (snapshot.textId !== OFF) engine.select('text', OFF);
    } else if (prefs.textLang) {
      const match = snapshot.text.find((t) => sameLanguage(t.lang, prefs.textLang));
      if (match && match.id !== snapshot.textId) engine.select('text', match.id);
    }
  }
  if (!applied.audio && snapshot.audio.length > 1) {
    applied.audio = true;
    const match = prefs.audioLang && snapshot.audio.find((t) => sameLanguage(t.lang, prefs.audioLang));
    if (match && match.id !== snapshot.audioId) engine.select('audio', match.id);
  }
}
