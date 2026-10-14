import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { LogOut, ShieldCheck } from 'lucide-react';
import { useAuth } from '@/core/auth/AuthProvider';
import { Slot } from '@/core/featureKit';
import { Button } from '@/shared/components/Button/Button';
import { Page, Panel } from '@/shared/components/Page/Page';
import { useToast } from '@/shared/components/Toast/Toast';
import { changePasswordSchema } from '../schema';
import { PasswordInput } from './PasswordInput';
import { useT } from '../i18n';

export default function AccountPage() {
  const t = useT();
  const { user, changePassword, logoutEverywhere } = useAuth();
  const toast = useToast();
  const { register, handleSubmit, reset, formState } = useForm({ resolver: zodResolver(changePasswordSchema) });

  const onSubmit = async ({ current, next }) => {
    try {
      await changePassword(current, next);
      reset();
      toast.success(t('account.changed'));
    } catch (err) {
      toast.error(err.userMessage);
    }
  };

  return (
    <Page title={t('account.title')} subtitle={`${user?.username}${user?.email ? ` · ${user.email}` : ''}`} width="narrow">
      {/* Other features add sections here (subscription summary, devices …). */}
      <Slot name="account.sections" />
      <Panel title={t('account.changePassword')}>
        <form onSubmit={handleSubmit(onSubmit)} style={{ display: 'grid', gap: '0.75rem' }} noValidate>
          <PasswordInput placeholder={t('field.current')} autoComplete="current-password" aria-label={t('field.current')} {...register('current')} />
          {formState.errors.current && <span className="field-error">{t(formState.errors.current.message)}</span>}
          <PasswordInput placeholder={t('field.next')} autoComplete="new-password" aria-label={t('field.next')} {...register('next')} />
          {formState.errors.next && <span className="field-error">{t(formState.errors.next.message)}</span>}
          <PasswordInput placeholder={t('field.nextAgain')} autoComplete="new-password" aria-label={t('field.nextAgain')} {...register('confirm')} />
          {formState.errors.confirm && <span className="field-error">{t(formState.errors.confirm.message)}</span>}
          <div>
            <Button type="submit" disabled={formState.isSubmitting}>
              <ShieldCheck size={16} style={{ marginRight: 6 }} /> {t('account.update')}
            </Button>
          </div>
        </form>
      </Panel>
      <Panel title={t('account.sessions')}>
        <p style={{ color: 'var(--color-text-secondary)', marginTop: 0 }}>
          {t('account.sessionsBody')}
        </p>
        <Button variant="danger" onClick={() => logoutEverywhere()}>
          <LogOut size={16} style={{ marginRight: 6 }} /> {t('account.signOutAll')}
        </Button>
      </Panel>
    </Page>
  );
}
