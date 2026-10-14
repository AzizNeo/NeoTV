import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { MailCheck } from 'lucide-react';
import { api } from '@/core/api/client';
import { useAuth } from '@/core/auth/AuthProvider';
import { Button } from '@/shared/components/Button/Button';
import { Panel } from '@/shared/components/Page/Page';
import { useToast } from '@/shared/components/Toast/Toast';
import { changeEmailSchema } from '../schema';
import { PasswordInput } from '../pages/PasswordInput';
import { useT } from '../i18n';

/** Contribution to `account.sections`: nothing changes until the link in the new inbox is opened. */
export function EmailChangeSection() {
  const t = useT();
  const { user } = useAuth();
  const toast = useToast();
  const [pendingTo, setPendingTo] = useState(null);
  const { register, handleSubmit, reset, formState } = useForm({ resolver: zodResolver(changeEmailSchema) });

  const onSubmit = async ({ email, password }) => {
    try {
      await api.call('identity_request_email_change', { body: { new_email: email, password } });
      reset();
      setPendingTo(email);
    } catch (err) {
      toast.error(err.userMessage);
    }
  };

  return (
    <Panel title={t(user?.email ? 'email.change' : 'email.add')}>
      {pendingTo && (
        <p role="status" style={{ marginTop: 0 }}>
          <MailCheck size={16} aria-hidden="true" style={{ verticalAlign: 'text-bottom', marginRight: 6 }} />
          {t('email.pending', { email: pendingTo })}
        </p>
      )}
      <form onSubmit={handleSubmit(onSubmit)} style={{ display: 'grid', gap: '0.75rem' }} noValidate>
        <input
          className="input-field"
          type="email"
          placeholder={t('field.newEmail')}
          autoComplete="email"
          aria-label={t('field.newEmail')}
          {...register('email')}
        />
        {formState.errors.email && <span className="field-error">{t(formState.errors.email.message)}</span>}
        <PasswordInput placeholder={t('field.current')} autoComplete="current-password" aria-label={t('email.currentFor')} {...register('password')} />
        {formState.errors.password && <span className="field-error">{t(formState.errors.password.message)}</span>}
        <div>
          <Button type="submit" variant="secondary" disabled={formState.isSubmitting}>{t('email.send')}</Button>
        </div>
      </form>
    </Panel>
  );
}
