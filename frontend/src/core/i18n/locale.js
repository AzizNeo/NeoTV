import { useSyncExternalStore } from 'react';

/**
 * The interface language: a tiny external store (no React context needed), so code outside
 * components — API errors, the API client's Accept-Language header — reads the same value.
 *
 * Choice order: what the viewer picked on this device → the browser's languages → Turkish.
 */
export const LOCALES = Object.freeze({ tr: 'Türkçe', en: 'English' });
export const DEFAULT_LOCALE = 'tr';
const STORAGE_KEY = 'neotv.locale';

export class UnknownLocaleError extends Error {
  name = 'UnknownLocaleError';
  constructor(locale) {
    super(`unknown locale '${locale}' (supported: ${Object.keys(LOCALES).join(', ')})`);
  }
}

function detect() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved in LOCALES) return saved;
  } catch {
    /* storage blocked: fall through to the browser languages */
  }
  const wanted = typeof navigator === 'undefined' ? [] : (navigator.languages ?? [navigator.language]);
  for (const tag of wanted) {
    const base = String(tag).toLowerCase().split('-')[0];
    if (base in LOCALES) return base;
  }
  return DEFAULT_LOCALE;
}

let current = detect();
const listeners = new Set();

function apply() {
  if (typeof document !== 'undefined') document.documentElement.lang = current; // screen readers, hyphenation, fonts
}
apply();

export const getLocale = () => current;

export function setLocale(next) {
  if (!(next in LOCALES)) throw new UnknownLocaleError(next);
  if (next === current) return;
  current = next;
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* not remembered — still applied for this visit */
  }
  apply();
  for (const listener of listeners) listener();
}

export function subscribeLocale(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** `{ locale, setLocale, locales }` — re-renders the caller when the language changes. */
export function useLocale() {
  const locale = useSyncExternalStore(subscribeLocale, getLocale, () => DEFAULT_LOCALE);
  return { locale, setLocale, locales: LOCALES };
}
