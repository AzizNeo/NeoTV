import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render } from '@testing-library/react';
import { getLocale, setLocale } from '@/core/i18n';
import { LocaleSync } from './LocaleSync';

const auth = vi.hoisted(() => ({ value: { isAuthenticated: false, user: null } }));
const call = vi.hoisted(() => vi.fn(() => Promise.resolve({})));
vi.mock('@/core/auth/AuthProvider', () => ({ useAuth: () => auth.value }));
vi.mock('@/core/api/client', () => ({ api: { call } }));

const signIn = (locale) => (auth.value = { isAuthenticated: true, user: { id: 7, locale } });

describe('account language sync', () => {
  beforeEach(() => {
    call.mockClear();
    auth.value = { isAuthenticated: false, user: null };
  });

  it('a device where nobody chose a language adopts the account language, without echoing it back', () => {
    localStorage.removeItem('neotv.locale'); // only the browser's guess so far
    signIn('en');
    render(<LocaleSync />);
    expect(getLocale()).toBe('en');
    expect(call).not.toHaveBeenCalled();
  });

  it('a choice made on this device wins and is saved; every later switch is saved too', () => {
    setLocale('en'); // e.g. picked on the sign-in screen
    signIn('tr');
    render(<LocaleSync />);
    expect(getLocale()).toBe('en');
    expect(call).toHaveBeenLastCalledWith('identity_set_locale', { body: { locale: 'en' } });
    act(() => setLocale('tr'));
    expect(call).toHaveBeenLastCalledWith('identity_set_locale', { body: { locale: 'tr' } });
    expect(call).toHaveBeenCalledTimes(2);
  });
});
