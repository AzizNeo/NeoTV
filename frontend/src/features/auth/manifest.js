import { UserCog } from 'lucide-react';
import { defineFeature } from '@/core/featureKit';
import { EmailChangeSection } from './components/EmailChangeSection';
import { EmailVerificationNotice } from './components/EmailVerificationNotice';

export default defineFeature({
  id: 'auth',
  backendModule: 'identity',
  routes: [
    { path: '/login', lazy: () => import('./pages/LoginPage'), guard: 'public', layout: 'bare' },
    { path: '/register', lazy: () => import('./pages/RegisterPage'), guard: 'public', layout: 'bare' },
    { path: '/forgot-password', lazy: () => import('./pages/ForgotPasswordPage'), guard: 'public', layout: 'bare' },
    // Opened from e-mail: must work whether or not this browser is signed in.
    { path: '/reset-password', lazy: () => import('./pages/ResetPasswordPage'), guard: 'any', layout: 'bare' },
    { path: '/verify-email', lazy: () => import('./pages/VerifyEmailPage'), guard: 'any', layout: 'bare' },
    { path: '/confirm-email-change', lazy: () => import('./pages/ConfirmEmailChangePage'), guard: 'any', layout: 'bare' },
    { path: '/revert-email-change', lazy: () => import('./pages/RevertEmailChangePage'), guard: 'any', layout: 'bare' },
    { path: '/account', lazy: () => import('./pages/AccountPage') },
  ],
  nav: [{ to: '/account', label: 'Hesap', icon: UserCog, order: 900, section: 'account' }],
  slots: ['account.sections', 'shell.user'],
  contributes: [
    { slot: 'account.sections', component: EmailVerificationNotice, order: 0 },
    { slot: 'account.sections', component: EmailChangeSection, order: 50 },
  ],
});
