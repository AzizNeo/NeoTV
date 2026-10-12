import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { buildRegistry } from '@/core/featureKit';
import { FEATURES } from '@/features';
import { HeroBillboard } from './components/HeroBillboard';
import { TitleCard } from './components/TitleCard';

const call = vi.fn();
vi.mock('@/core/api/client', () => ({ api: { call: (...args) => call(...args) } }));

const card = (slug, extra = {}) => ({
  slug, kind: 'movie', name: slug.toUpperCase(), year: 2010, rating: 'teen', runtime_minutes: 15, season_count: 0,
  genres: ['Animasyon'], poster_url: null, backdrop_url: null, available: true, ...extra,
});

const ui = (node) =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );

beforeEach(() => call.mockReset());

describe('HeroBillboard', () => {
  it('plays the featured source and lets the viewer switch titles', async () => {
    call.mockResolvedValue([
      { card: card('sintel'), synopsis: 'Ejderha', play_ref: 'catalog:2' },
      { card: card('bunny'), synopsis: 'Tavşan', play_ref: 'catalog:1' },
    ]);
    const onSelect = vi.fn();
    ui(<HeroBillboard onSelect={onSelect} />);
    expect(await screen.findByRole('heading', { name: 'SINTEL' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Ayrıntılar/ })).toHaveAttribute('href', '/title/sintel');

    await userEvent.click(screen.getByRole('button', { name: 'BUNNY' }));
    expect(screen.getByRole('heading', { name: 'BUNNY' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Oynat/ }));
    expect(onSelect).toHaveBeenCalledWith({ ref: 'catalog:1', title: 'BUNNY' });
  });

  it('renders nothing when nothing is featured', async () => {
    call.mockResolvedValue([]);
    const { container } = ui(<HeroBillboard />);
    await vi.waitFor(() => expect(call).toHaveBeenCalled());
    await vi.waitFor(() => expect(container.querySelector('section')).toBeNull());
  });
});

describe('TitleCard', () => {
  it('links to the detail page and marks unplayable titles', () => {
    ui(<TitleCard card={card('tears', { available: false, kind: 'series', season_count: 2 })} />);
    const link = screen.getByRole('link', { name: 'TEARS (şu an izlenemiyor)' });
    expect(link).toHaveAttribute('href', '/title/tears');
    expect(link).toHaveTextContent('2010 · 2 sezon');
  });
});

describe('titles feature', () => {
  it('plugs into the home slots, and drops out when the backend module is off', () => {
    const on = buildRegistry(FEATURES);
    expect(on.slots.get('home.hero').map((c) => c.feature)).toEqual(['titles']);
    const off = buildRegistry(FEATURES, { backendModules: ['identity', 'profile', 'playback', 'catalog', 'live', 'library'] });
    expect(off.has('titles')).toBe(false);
    expect(off.slots.get('home.hero') ?? []).toEqual([]);
  });
});
