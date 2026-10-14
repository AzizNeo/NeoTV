/**
 * Keyboard shortcuts — one list drives both the key handler and the "?" help screen, so the help
 * can never drift from what the keys really do.
 *
 * A shortcut: { keys: string[] (KeyboardEvent.key values), label, run(key), display? }.
 * Extra shortcuts (from the screen that opened the player, e.g. live TV) win on conflicts:
 * live TV takes ↑/↓ for channels, and volume moves to +/−.
 */
export const DIGITS = ['0', '1', '2', '3', '4', '5', '6', '7', '8', '9'];

const KEY_NAMES = {
  ArrowLeft: '←',
  ArrowRight: '→',
  ArrowUp: '↑',
  ArrowDown: '↓',
  PageUp: 'PgUp',
  PageDown: 'PgDn',
  Escape: 'Esc',
};

/** How a key is printed in the help; `space` is the only one with a word in it (translated by the caller). */
export function keyName(key, { space = 'Space', locale = 'tr' } = {}) {
  if (key === ' ') return space;
  if (KEY_NAMES[key]) return KEY_NAMES[key];
  if (/^[A-Z]$/.test(key)) return `Shift+${key}`; // "N" is what the browser reports for Shift+N
  return key.length === 1 ? key.toLocaleUpperCase(locale) : key;
}

export function resolveShortcuts(defaults, extra = [], names = {}) {
  const taken = new Set(extra.flatMap((s) => s.keys));
  const merged = [
    ...defaults
      .map((s) => {
        const keys = s.keys.filter((k) => !taken.has(k));
        return { ...s, keys, display: keys.length === s.keys.length ? s.display : undefined };
      })
      .filter((s) => s.keys.length),
    ...extra,
  ];
  const byKey = new Map();
  for (const s of merged) for (const k of s.keys) byKey.set(k, s);
  return { byKey, list: merged.map((s) => ({ keys: s.display ? [s.display] : s.keys.map((k) => keyName(k, names)), label: s.label })) };
}

/** True when a key press belongs to something else: a text field, or a browser/OS shortcut. */
export function ignoreKey(event) {
  if (event.ctrlKey || event.metaKey || event.altKey) return true;
  const el = event.target;
  return Boolean(el && (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.isContentEditable));
}
