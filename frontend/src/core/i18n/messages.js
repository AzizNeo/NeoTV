import { useMemo } from 'react';
import { DEFAULT_LOCALE, LOCALES, getLocale, useLocale } from './locale';

/**
 * Message catalogs — every feature owns its texts, in every language, next to its code:
 *
 *   export const messages = defineMessages('player', { tr: { settings: { title: 'Ayarlar' } }, en: {…} });
 *   const t = useTranslation(messages);   t('settings.title')   t('next.in', { s: 5 })
 *
 * A catalog that is incomplete fails *when it is defined* (app start, and every test that imports
 * it) with a named MessageCatalogError: a language missing, a key missing in one language, or a
 * placeholder dropped by a translation ("{count}" in Turkish but not in English).
 *
 * Values: a string with `{name}` placeholders, or a plural object `{ one, other }` chosen by
 * `params.count` through Intl.PluralRules (Turkish only uses `other`).
 */
export class MessageCatalogError extends Error {
  name = 'MessageCatalogError';
  constructor(ns, detail) {
    super(`[messages:${ns}] ${detail}`);
    this.namespace = ns;
  }
}

const PLURAL_FORMS = new Set(['zero', 'one', 'two', 'few', 'many', 'other']);
const isPlural = (v) => v && typeof v === 'object' && Object.keys(v).length > 0 && Object.keys(v).every((k) => PLURAL_FORMS.has(k));
const placeholders = (v) => new Set([...(typeof v === 'string' ? [v] : Object.values(v)).join(' ').matchAll(/\{(\w+)\}/g)].map((m) => m[1]));

function flatten(ns, tree, prefix = '', out = new Map()) {
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === 'string') out.set(path, value);
    else if (isPlural(value)) {
      if (!('other' in value)) throw new MessageCatalogError(ns, `plural '${path}' needs an 'other' form`);
      out.set(path, Object.freeze({ ...value }));
    } else if (value && typeof value === 'object') flatten(ns, value, path, out);
    else throw new MessageCatalogError(ns, `'${path}' must be a string, a plural object or a group`);
  }
  return out;
}

export function defineMessages(ns, catalogs) {
  const tables = {};
  for (const locale of Object.keys(LOCALES)) {
    if (!catalogs?.[locale]) throw new MessageCatalogError(ns, `no '${locale}' messages`);
    tables[locale] = flatten(ns, catalogs[locale]);
  }
  const base = tables[DEFAULT_LOCALE];
  for (const [locale, table] of Object.entries(tables)) {
    const missing = [...base.keys()].filter((k) => !table.has(k));
    const extra = [...table.keys()].filter((k) => !base.has(k));
    if (missing.length) throw new MessageCatalogError(ns, `'${locale}' is missing: ${missing.join(', ')}`);
    if (extra.length) throw new MessageCatalogError(ns, `'${locale}' has keys '${DEFAULT_LOCALE}' lacks: ${extra.join(', ')}`);
    for (const [key, value] of table) {
      const want = [...placeholders(base.get(key))].sort().join();
      const got = [...placeholders(value)].sort().join();
      if (want !== got) throw new MessageCatalogError(ns, `'${locale}.${key}' placeholders {${got}} ≠ {${want}}`);
    }
  }
  const catalog = {
    ns,
    tables: Object.freeze(tables),
    /** A label to translate later (e.g. a nav item in a manifest). Unknown keys fail now, not on screen. */
    ref(key) {
      if (!base.has(key)) throw new MessageCatalogError(ns, `ref to unknown key '${key}'`);
      return Object.freeze({ catalog, key });
    },
  };
  return Object.freeze(catalog);
}

const pluralRules = new Map();
const numberFormats = new Map();
const cached = (map, locale, make) => map.get(locale) ?? map.set(locale, make()).get(locale);
const warned = new Set();

export function translate(catalog, key, params = {}, locale = getLocale()) {
  let value = catalog.tables[locale]?.get(key);
  if (value === undefined) {
    // Only reachable with a key the catalog never had (a typo in code): visible, never a crash.
    const id = `${catalog.ns}.${key}`;
    if (!warned.has(id) && import.meta.env?.DEV) console.warn(`[i18n] unknown message '${id}'`);
    warned.add(id);
    return id;
  }
  if (typeof value === 'object') {
    const form = cached(pluralRules, locale, () => new Intl.PluralRules(locale)).select(Number(params.count ?? 0));
    value = value[form] ?? value.other;
  }
  return value.replace(/\{(\w+)\}/g, (match, name) => {
    const v = params[name];
    if (v === undefined || v === null) return match;
    return typeof v === 'number' ? cached(numberFormats, locale, () => new Intl.NumberFormat(locale)).format(v) : String(v);
  });
}

/** `label` is plain text or a `catalog.ref(key)` descriptor. */
export function labelOf(label, locale = getLocale()) {
  return label && typeof label === 'object' ? translate(label.catalog, label.key, {}, locale) : label;
}

/** `t(key, params)` bound to a catalog and the current language (re-renders on change). */
export function useTranslation(catalog) {
  const { locale } = useLocale();
  return useMemo(() => Object.assign((key, params) => translate(catalog, key, params, locale), { locale }), [catalog, locale]);
}
