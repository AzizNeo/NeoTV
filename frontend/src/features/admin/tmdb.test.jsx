import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '@/shared/components/Toast/Toast';
import TmdbSection from './sections/TmdbSection';
import { slugify, tmdbPage } from './sections/tmdb';

const call = vi.fn();
vi.mock('@/core/api/client', () => ({ api: { call: (...args) => call(...args) } }));

const ATTRIBUTION = 'This product uses the TMDB API but is not endorsed or certified by TMDB.';
const HIT = { tmdb_id: 45745, kind: 'movie', name: 'Sintel', original_name: 'Sintel', year: 2010, overview: 'Bir kız ve ejderhası.', poster_url: 'https://image.tmdb.org/t/p/w500/x.jpg' };

function backend({ configured = true, links = [], titles = [] } = {}) {
  call.mockImplementation(async (op, args) => {
    switch (op) {
      case 'tmdb_status': return { configured, attribution: ATTRIBUTION };
      case 'tmdb_links': return links;
      case 'tmdb_search': return [HIT];
      case 'titles_admin_list': return { items: titles, next_cursor: null };
      case 'tmdb_link': return { slug: args.params.slug, tmdb_id: 45745, kind: 'movie', synced_at: '2026-10-15T10:00:00Z', created: !titles.length };
      default: throw new Error(`unexpected ${op}`);
    }
  });
}

const ui = () => render(
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ToastProvider>
      <MemoryRouter><TmdbSection /></MemoryRouter>
    </ToastProvider>
  </QueryClientProvider>,
);

describe('TMDB helpers', () => {
  it('slugify matches the backend (Turkish letters, accents, length)', () => {
    expect(slugify('Çılgın Şehir 2')).toBe('cilgin-sehir-2');
    expect(slugify('  Amélie — Le Fabuleux Destin!  ')).toBe('amelie-le-fabuleux-destin');
    expect(slugify('a'.repeat(79) + ' b')).toBe('a'.repeat(79));
  });

  it('links to the right TMDB page per kind', () => {
    expect(tmdbPage({ kind: 'movie', tmdb_id: 1 })).toBe('https://www.themoviedb.org/movie/1');
    expect(tmdbPage({ kind: 'series', tmdb_id: 2 })).toBe('https://www.themoviedb.org/tv/2');
  });
});

describe('TmdbSection', () => {
  beforeEach(() => { call.mockReset(); });

  it('without a token: explains the setup, hides search, still lists links and the attribution', async () => {
    backend({ configured: false, links: [{ slug: 'sintel', tmdb_id: 45745, kind: 'movie', synced_at: '2026-10-15T10:00:00Z' }] });
    ui();
    expect(await screen.findByText('TMDB yapılandırılmamış')).toBeInTheDocument();
    expect(screen.queryByRole('search')).not.toBeInTheDocument();
    expect(await screen.findByRole('link', { name: 'sintel' })).toHaveAttribute('href', '/title/sintel');
    expect(screen.queryByRole('button', { name: 'TMDB\'den yenile' })).not.toBeInTheDocument();
    expect(screen.getByText(/TMDB tarafından onaylanmış veya sertifikalandırılmış değildir/)).toBeInTheDocument();
  });

  it('search → import a new movie with a play source', async () => {
    backend();
    ui();
    fireEvent.change(await screen.findByRole('searchbox', { name: 'Ad' }), { target: { value: ' sintel ' } });
    fireEvent.click(screen.getByRole('button', { name: 'Bul' }));
    fireEvent.click(await screen.findByRole('button', { name: 'İçe aktar' }));
    expect(call).toHaveBeenCalledWith('tmdb_search', { query: { query: 'sintel', kind: 'movie', year: undefined } });

    expect(await screen.findByText('Yeni başlık')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Oynatma kaynağı (isteğe bağlı)'), { target: { value: 'vod:sintel' } });
    fireEvent.click(screen.getByRole('button', { name: 'Oluştur' }));
    await waitFor(() => expect(call).toHaveBeenCalledWith('tmdb_link', {
      params: { slug: 'sintel' }, body: { tmdb_id: 45745, kind: 'movie', play_ref: 'vod:sintel' },
    }));
    expect(await screen.findByText('“sintel” TMDB\'den oluşturuldu.')).toBeInTheDocument();
  });

  it('an existing title is enriched — no play source asked, editorial fields promised safe', async () => {
    backend({ titles: [{ slug: 'sintel', name: 'Sintel', kind: 'movie' }] });
    ui();
    fireEvent.change(await screen.findByRole('searchbox', { name: 'Ad' }), { target: { value: 'sintel' } });
    fireEvent.click(screen.getByRole('button', { name: 'Bul' }));
    fireEvent.click(await screen.findByRole('button', { name: 'İçe aktar' }));
    expect(await screen.findByText('Mevcut başlık')).toBeInTheDocument();
    expect(screen.queryByLabelText('Oynatma kaynağı (isteğe bağlı)')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Bilgileri güncelle' }));
    await waitFor(() => expect(call).toHaveBeenCalledWith('tmdb_link', {
      params: { slug: 'sintel' }, body: { tmdb_id: 45745, kind: 'movie', play_ref: undefined },
    }));
  });
});
