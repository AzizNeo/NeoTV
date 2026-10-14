import { useMemo } from 'react';
import { getLocale, useLocale } from './locale';

/**
 * Dates, times and money in the viewer's language (Intl does the work; formatters are cached).
 * "14 Eki 2026 21:05" / "Oct 14, 2026, 9:05 PM", "₺149,90" / "TRY 149.90".
 */
const cache = new Map();
function formatter(Kind, locale, options) {
  const key = `${Kind.name}|${locale}|${JSON.stringify(options)}`;
  if (!cache.has(key)) cache.set(key, new Kind(locale, options));
  return cache.get(key);
}

const asDate = (value) => (value instanceof Date ? value : new Date(value));

export function formatTime(value, locale = getLocale()) {
  return formatter(Intl.DateTimeFormat, locale, { hour: '2-digit', minute: '2-digit' }).format(asDate(value));
}

export function formatDateTime(value, { dateStyle = 'medium', timeStyle = 'short' } = {}, locale = getLocale()) {
  return value ? formatter(Intl.DateTimeFormat, locale, { dateStyle, timeStyle }).format(asDate(value)) : '—';
}

export function formatDate(value, { dateStyle = 'long' } = {}, locale = getLocale()) {
  return value ? formatter(Intl.DateTimeFormat, locale, { dateStyle }).format(asDate(value)) : null;
}

/** Amounts arrive in minor units (kuruş / cents). */
export function formatMoney(minor, currency, locale = getLocale()) {
  return formatter(Intl.NumberFormat, locale, { style: 'currency', currency }).format(minor / 100);
}

/** The formatters bound to the current language (re-renders on change). */
export function useFormat() {
  const { locale } = useLocale();
  return useMemo(
    () => ({
      time: (v) => formatTime(v, locale),
      dateTime: (v, o) => formatDateTime(v, o, locale),
      date: (v, o) => formatDate(v, o, locale),
      money: (minor, currency) => formatMoney(minor, currency, locale),
    }),
    [locale],
  );
}
