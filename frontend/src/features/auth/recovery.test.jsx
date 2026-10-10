import { StrictMode } from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { readLinkToken } from './hooks/useLinkToken';

const call = vi.fn();
vi.mock('@/core/api/client', () => ({ api: { call: (...args) => call(...args) } }));
vi.mock('@/core/auth/AuthProvider', () => ({
  useAuth: () => ({ isAuthenticated: false, reloadUser: vi.fn(), forgetSession: vi.fn() }),
}));
vi.mock('@/shared/components/Toast/Toast', () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn() }) }));

const TOKEN = 'A'.repeat(43);
const page = (ui) => render(<StrictMode><MemoryRouter>{ui}</MemoryRouter></StrictMode>);

beforeEach(() => {
  call.mockReset();
  window.history.replaceState(null, '', '/');
});

describe('readLinkToken', () => {
  it('reads the fragment and rejects malformed values', () => {
    expect(readLinkToken(`#token=${TOKEN}`)).toBe(TOKEN);
    expect(readLinkToken('#token=short')).toBeNull();
    expect(readLinkToken('#token=<script>' + 'x'.repeat(30))).toBeNull();
    expect(readLinkToken('')).toBeNull();
  });
});

describe('VerifyEmailPage', () => {
  it('submits the single-use link exactly once (StrictMode) and scrubs it from the URL', async () => {
    window.history.replaceState(null, '', `/verify-email#token=${TOKEN}`);
    call.mockResolvedValue(null);
    const { default: VerifyEmailPage } = await import('./pages/VerifyEmailPage');
    page(<VerifyEmailPage />);
    expect(await screen.findByText(/doğrulandı/)).toBeInTheDocument();
    expect(call).toHaveBeenCalledTimes(1);
    expect(call).toHaveBeenCalledWith('identity_verify_email', { body: { token: TOKEN } });
    expect(window.location.hash).toBe('');
  });

  it('explains a missing link without calling the API', async () => {
    const { default: VerifyEmailPage } = await import('./pages/VerifyEmailPage');
    page(<VerifyEmailPage />);
    expect(screen.getByRole('alert')).toHaveTextContent('Bağlantı eksik');
    expect(call).not.toHaveBeenCalled();
  });
});

describe('ForgotPasswordPage', () => {
  it('shows the same neutral confirmation after submitting', async () => {
    call.mockResolvedValue(null);
    const { default: ForgotPasswordPage } = await import('./pages/ForgotPasswordPage');
    page(<ForgotPasswordPage />);
    await userEvent.type(screen.getByPlaceholderText('E-posta'), 'ali@example.com');
    await userEvent.click(screen.getByRole('button', { name: 'Bağlantı gönder' }));
    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('İsteğiniz alındı'));
    expect(call).toHaveBeenCalledWith('identity_forgot_password', { body: { email: 'ali@example.com' } });
  });
});
