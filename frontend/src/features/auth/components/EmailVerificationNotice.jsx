import { useState } from 'react';
import { MailWarning } from 'lucide-react';
import { api } from '@/core/api/client';
import { useAuth } from '@/core/auth/AuthProvider';
import { Button } from '@/shared/components/Button/Button';
import { Panel } from '@/shared/components/Page/Page';
import { useToast } from '@/shared/components/Toast/Toast';
import { useT } from '../i18n';

/** Contribution to `account.sections`: shown only while the address is unverified. */
export function EmailVerificationNotice() {
  const t = useT();
  const { user } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (!user?.email || user.email_verified) return null;

  const resend = async () => {
    setBusy(true);
    try {
      await api.call('identity_send_email_verification');
      toast.success(t('email.verificationSent', { email: user.email }));
    } catch (err) {
      toast.error(err.userMessage);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title={t('email.unverified')}>
      <p style={{ color: 'var(--color-text-secondary)', marginTop: 0 }}>
        <MailWarning size={16} aria-hidden="true" style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />
        {t('email.unverifiedBody', { email: user.email })}
      </p>
      <Button variant="secondary" onClick={resend} disabled={busy}>{t('email.sendVerification')}</Button>
    </Panel>
  );
}
