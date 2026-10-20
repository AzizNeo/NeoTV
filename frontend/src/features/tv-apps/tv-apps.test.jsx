import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { ToastProvider } from '@/shared/components/Toast/Toast';
import TvAppsPage from './pages/TvAppsPage';
import { signInDetails } from './signIn';

const call = vi.fn();
vi.mock('@/core/api/client', () => ({ api: { call: (...args) => call(...args) } }));
const profile = vi.hoisted(() => ({ value: null }));
vi.mock('@/features/profiles', () => ({ useProfile: () => profile.value }));

const ADULT = { id: 1, name: 'Aziz', is_kids: false, has_pin: false };
const KIDS = { id: 2, name: 'Çocuk', is_kids: true, has_pin: false };
const LOCKED = { id: 3, name: 'Özel', is_kids: false, has_pin: true };
const CREDENTIAL = {
  id: 7, label: 'Salon TV', username: 'abcdefghjk', profile_id: 1, profile_name: 'Aziz',
  created_at: '2026-10-18T10:00:00Z', last_used_at: null,
};
const ISSUED = { credential: { ...CREDENTIAL, id: 8, label: 'Yatak odası' }, server_url: 'https://tv.example.com', password: 'aaaabbbbcccc' };

function ui(current = ADULT, profiles = [ADULT, KIDS, LOCKED]) {
  profile.value = { current, profiles };
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <ToastProvider>
        <MemoryRouter><TvAppsPage /></MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe('signInDetails', () => {
  it('lists what an Xtream app asks for, with encoded M3U and EPG URLs', () => {
    expect(signInDetails({ ...ISSUED, password: 'a&b' })).toEqual([
      ['server', 'https://tv.example.com'],
      ['username', 'abcdefghjk'],
      ['password', 'a&b'],
      ['m3u', 'https://tv.example.com/get.php?username=abcdefghjk&password=a%26b&type=m3u_plus&output=m3u8'],
      ['epg', 'https://tv.example.com/xmltv.php?username=abcdefghjk&password=a%26b'],
    ]);
  });
});

describe('TV apps page', () => {
  beforeEach(() => {
    call.mockReset();
    call.mockImplementation(async (op) => {
      if (op === 'xtream_list_credentials') return [CREDENTIAL];
      if (op === 'xtream_issue_credential') return ISSUED;
      if (op === 'xtream_revoke_credential') return null;
      throw new Error(`unexpected ${op}`);
    });
  });

  it('lists credentials without any secret, and says when one was never used', async () => {
    ui();
    expect(await screen.findByText('Salon TV')).toBeInTheDocument();
    expect(screen.getByText('abcdefghjk')).toBeInTheDocument();
    expect(screen.getByText('Henüz kullanılmadı', { exact: false })).toBeInTheDocument();
    expect(screen.getByText(/NeoTV başka içerik sağlamaz/)).toBeInTheDocument();
  });

  it('creates a credential for a profile and shows the password once', async () => {
    ui();
    fireEvent.click(await screen.findByRole('button', { name: /TV uygulaması ekle/ }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText('Cihaz adı'), { target: { value: '  Yatak odası ' } });
    const select = within(dialog).getByLabelText('Profil');
    expect(within(select).getByRole('option', { name: /Özel \(PIN korumalı/ })).toBeDisabled(); // its PIN was not entered
    fireEvent.change(select, { target: { value: '2' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Oluştur' }));
    await waitFor(() => expect(call).toHaveBeenCalledWith('xtream_issue_credential', { body: { label: 'Yatak odası', profile_id: 2 } }));

    const shown = await screen.findByRole('dialog', { name: 'Giriş bilgileri hazır' });
    expect(within(shown).getByRole('alert')).toHaveTextContent('yalnızca şimdi');
    expect(within(shown).getByText('aaaabbbbcccc')).toBeInTheDocument();
    expect(within(shown).getByRole('button', { name: 'Şifre kopyala' })).toBeInTheDocument();
    fireEvent.click(within(shown).getByRole('button', { name: 'Tamam, kaydettim' }));
    await waitFor(() => expect(screen.queryByText('aaaabbbbcccc')).not.toBeInTheDocument()); // gone for good
  });

  it('revokes after a confirmation', async () => {
    ui();
    fireEvent.click(await screen.findByRole('button', { name: 'Kaldır: Salon TV' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Kaldır' }));
    await waitFor(() => expect(call).toHaveBeenCalledWith('xtream_revoke_credential', { params: { credential_id: 7 } }));
  });

  it('on a kids profile, explains instead of calling the API', () => {
    ui(KIDS);
    expect(screen.getByText('Çocuk profilinde yönetilemez')).toBeInTheDocument();
    expect(call).not.toHaveBeenCalled();
  });
});
