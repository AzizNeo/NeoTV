import { describe, expect, it } from 'vitest';
import { act, render, screen } from '@testing-library/react';
import { MessageCatalogError, defineMessages, getLocale, labelOf, messageFor, setLocale, translate, useTranslation, UnknownLocaleError } from '.';

const ok = { tr: { hi: 'Merhaba {name}', items: { other: '{count} öğe' } }, en: { hi: 'Hello {name}', items: { one: '{count} item', other: '{count} items' } } };

describe('message catalogs', () => {
  it('refuse a gap at definition time, with a named error', () => {
    expect(() => defineMessages('x', { tr: { a: 'A' } })).toThrow(MessageCatalogError);
    expect(() => defineMessages('x', { tr: { a: 'A', b: 'B' }, en: { a: 'A' } })).toThrow(/'en' is missing: b/);
    expect(() => defineMessages('x', { tr: { a: '{n} tane' }, en: { a: 'some' } })).toThrow(/placeholders/);
    expect(() => defineMessages('x', { tr: { a: 'A' }, en: { a: 'A' } }).ref('nope')).toThrow(/unknown key 'nope'/);
  });

  it('interpolate, pick plural forms per language and format numbers per language', () => {
    const m = defineMessages('ok', ok);
    expect(translate(m, 'hi', { name: 'Aziz' }, 'tr')).toBe('Merhaba Aziz');
    expect(translate(m, 'items', { count: 1 }, 'en')).toBe('1 item');
    expect(translate(m, 'items', { count: 1200 }, 'en')).toBe('1,200 items');
    expect(translate(m, 'items', { count: 1200 }, 'tr')).toBe('1.200 öğe');
    expect(translate(m, 'missing', {}, 'tr')).toBe('ok.missing'); // visible, never a crash
    expect(labelOf(m.ref('hi'), 'en')).toBe('Hello {name}');
  });

  it('every catalog in the app is complete in every language', () => {
    // Importing a catalog runs defineMessages, which throws on any gap.
    const modules = import.meta.glob(['/src/**/i18n.js', '/src/core/i18n/errors.js'], { eager: true });
    const catalogs = Object.values(modules).map((m) => m.messages ?? m.errorMessages);
    expect(catalogs.length).toBeGreaterThan(5);
    expect(new Set(catalogs.map((c) => c.ns)).size).toBe(catalogs.length); // namespaces are unique
  });
});

describe('locale', () => {
  it('switching re-renders translated components, persists, and drives error texts', () => {
    const m = defineMessages('ui', ok);
    function Hello() {
      const t = useTranslation(m);
      return <p>{t('hi', { name: 'Aziz' })}</p>;
    }
    render(<Hello />);
    expect(screen.getByText('Merhaba Aziz')).toBeInTheDocument();
    act(() => setLocale('en'));
    expect(screen.getByText('Hello Aziz')).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('en');
    expect(localStorage.getItem('neotv.locale')).toBe('en');
    expect(messageFor('PIN_INVALID')).toBe('Wrong PIN.');
    expect(() => setLocale('de')).toThrow(UnknownLocaleError);
    expect(getLocale()).toBe('en');
  });
});
