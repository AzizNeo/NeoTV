import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import OverviewSection from './sections/OverviewSection';

const call = vi.fn();
vi.mock('@/core/api/client', () => ({ api: { call: (...args) => call(...args) } }));

// Every figure admin_stats can return (app/modules/admin/services.py → dashboard()).
const DASHBOARD = {
  users: { total: 12, active: 11, new_last_24h: 3 },
  sessions: { active_now: 4 },
  catalog: { channels: 9, live: 5, vod: 4, playlists: 2 },
  live: { channels: 3, on_air: 1, transcoding: 0 },
  devices: { active: 7 },
  plans: { free: 8, personal: 3, enterprise: 1 },
  drm: { protected_contents: 2, active_licenses: 1, issued_24h: 6, denied_24h: 0, keys_delivered_24h: 14 },
  generated_at: '2026-10-17T20:00:00+00:00',
};
const PLANS = [{ id: 'free', display_name: 'Free' }, { id: 'personal', display_name: 'Personal' }];

function ui() {
  call.mockImplementation(async (op) => {
    if (op === 'admin_stats') return DASHBOARD;
    if (op === 'billing_plans') return PLANS;
    throw new Error(`unexpected ${op}`);
  });
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <OverviewSection />
    </QueryClientProvider>,
  );
}

describe('admin overview', () => {
  it('labels every figure in the interface language — never a raw key', async () => {
    const { container } = ui();
    expect(await screen.findByText('Son 24 saatte yeni')).toBeInTheDocument();
    for (const label of ['Şu an açık yayın', 'İsteğe bağlı', 'Yayında', 'Aktif cihaz', 'Teslim edilen anahtar (24 sa)']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
    expect(container.textContent).not.toMatch(/admin\.stats\.|new last 24h|active now|_/);
  });

  it('names plan rows from the plan catalogue, falling back to the id', async () => {
    ui();
    expect(await screen.findByText('Personal')).toBeInTheDocument();
    expect(screen.getByText('Free')).toBeInTheDocument();
    expect(screen.getByText('enterprise')).toBeInTheDocument(); // not in the catalogue: shown as is
  });
});
