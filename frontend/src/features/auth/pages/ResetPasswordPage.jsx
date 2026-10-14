import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { api } from '@/core/api/client';
import { useAuth } from '@/core/auth/AuthProvider';
import { Button } from '@/shared/components/Button/Button';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { useToast } from '@/shared/components/Toast/Toast';
import { useLinkToken } from '../hooks/useLinkToken';
import { resetPasswordSchema } from '../schema';
import { PasswordInput } from './PasswordInput';
import styles from './AuthLayout.module.css';
import { useT } from '../i18n';
import { LanguageSwitch } from '@/core/i18n';

export default function ResetPasswordPage() {
  const t = useT();
  const token = useLinkToken();
  const navigate = useNavigate();
  const toast = useToast();
  const { isAuthenticated, forgetSession } = useAuth();
  const [error, setError] = useState('');
  const { register, handleSubmit, formState } = useForm({ resolver: zodResolver(resetPasswordSchema) });

  const onSubmit = async ({ password }) => {
    setError('');
    try {
      await api.call('identity_reset_password', { body: { token, new_password: password } });
      if (isAuthenticated) forgetSession(); // the server revoked every session, this tab included
      toast.success(t('reset.done'));
      navigate('/login', { replace: true });
    } catch (err) {
      setError(err.userMessage ?? t('reset.failed'));
    }
  };

  return (
    <main className={styles.screen}>
      <Link to="/login" className={styles.brand}>NeoTV</Link>
      <LanguageSwitch className={styles.lang} />
      <section className={styles.panel}>
        <h1>{t('reset.title')}</h1>
        {!token ? (
          <div className={styles.alert} role="alert">
            {t('reset.broken')} <Link to="/forgot-password">{t('reset.requestNew')}</Link>.
          </div>
        ) : (
          <>
            {error && (
              <div className={styles.alert} role="alert">
                {error} <Link to="/forgot-password">{t('reset.requestAgain')}</Link>
              </div>
            )}
            <form className={styles.form} onSubmit={handleSubmit(onSubmit)} noValidate>
              <PasswordInput placeholder={t('field.next')} autoComplete="new-password" aria-label={t('field.next')} autoFocus {...register('password')} />
              {formState.errors.password && <span className="field-error">{t(formState.errors.password.message)}</span>}
              <PasswordInput placeholder={t('field.nextAgain')} autoComplete="new-password" aria-label={t('field.nextAgain')} {...register('confirm')} />
              {formState.errors.confirm && <span className="field-error">{t(formState.errors.confirm.message)}</span>}
              <p className={styles.lead}>{t('reset.sessionsNote')}</p>
              <Button type="submit" size="lg" fullWidth disabled={formState.isSubmitting} style={{ marginTop: '0.5rem' }}>
                {formState.isSubmitting ? <Spinner size="sm" color="white" /> : t('reset.submit')}
              </Button>
            </form>
          </>
        )}
      </section>
    </main>
  );
}
