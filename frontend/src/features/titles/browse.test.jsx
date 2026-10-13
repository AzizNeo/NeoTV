import { describe, expect, it } from 'vitest';
import { fireEvent, render } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { buildRegistry } from '@/core/featureKit';
import { FEATURES } from '@/features';
import { readFilters, toApiQuery, writeFilters } from './browseParams';
import { SearchAction } from './components/SearchAction';

describe('browse URL ⇄ filters', () => {
  it('omits defaults, round-trips, and ignores garbage values', () => {
    expect(writeFilters({ q: '', genre: '', kind: '', sort: 'recent', decade: '' }).toString()).toBe('');
    const params = writeFilters({ q: 'ejderha', genre: 'animasyon', kind: 'movie', sort: 'year', decade: '2010' });
    expect(readFilters(params)).toEqual({ q: 'ejderha', genre: 'animasyon', kind: 'movie', sort: 'year', decade: '2010' });
    expect(readFilters(new URLSearchParams('kind=cartoon&sort=evil&decade=1066'))).toMatchObject({ kind: '', sort: 'recent', decade: '' });
  });

  it('maps to the API: decade → year range, 1-letter search not sent', () => {
    expect(toApiQuery(readFilters(new URLSearchParams('q=a&decade=2010')), 30)).toMatchObject({ search: undefined, year_from: 2010, year_to: 2019, per_page: 30 });
  });
});

function Where() {
  return <output>{useLocation().pathname}</output>;
}

describe('SearchAction', () => {
  const ui = () =>
    render(
      <MemoryRouter initialEntries={['/']}>
        <SearchAction />
        <input aria-label="other field" />
        <Routes>
          <Route path="*" element={<Where />} />
        </Routes>
      </MemoryRouter>,
    );

  it('"/" opens search — but not while typing in a field', () => {
    const { getByRole, getByLabelText } = ui();
    getByLabelText('other field').focus();
    fireEvent.keyDown(document, { key: '/' });
    expect(getByRole('status')).toHaveTextContent('/');
    getByLabelText('other field').blur();
    fireEvent.keyDown(document, { key: '/' });
    expect(getByRole('status')).toHaveTextContent('/browse');
  });
});

describe('search results slot', () => {
  it('live and catalog contribute channels; dropped with the storefront off', () => {
    expect(buildRegistry(FEATURES).slots.get('search.results').map((c) => c.feature)).toEqual(['live', 'catalog']);
    const off = buildRegistry(FEATURES, { backendModules: ['identity', 'profile', 'playback', 'catalog', 'live'] });
    expect(off.slots.get('search.results') ?? []).toEqual([]);
    expect(off.slots.get('shell.actions') ?? []).toEqual([]);
  });
});
