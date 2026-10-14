import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { MailCheck } from 'lucide-react';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { forgotPasswordSchema } from '../schema';
import styles from './AuthLayout.module.css';
import { useT } from '../i18n';
import { LanguageSwitch } from '@/core/i18n';

export default function ForgotPasswordPage() {
  const t = useT();
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');
  const { register, handleSubmit, formState } = useForm({ resolver: zodResolver(forgotPasswordSchema) });

  const onSubmit = async ({ email }) => {
    setError('');
    try {
      await api.call('identity_forgot_password', { body: { email } });
      setSent(true);
    } catch (err) {
      setError(err.userMessage ?? t('forgot.failed'));
    }
  };

  return (
    <main className={styles.screen}>
      <Link to="/login" className={styles.brand}>NeoTV</Link>
      <LanguageSwitch className={styles.lang} />
      <section className={styles.panel}>
        <h1>{t('forgot.title')}</h1>
        {sent ? (
          <div role="status">
            <p className={styles.ok}><MailCheck size={18} aria-hidden="true" /> {t('forgot.sent')}</p>
            <p className={styles.lead}>
              {t('forgot.sentBody')}
            </p>
          </div>
        ) : (
          <>
            <p className={styles.lead}>{t('forgot.lead')}</p>
            {error && <div className={styles.alert} role="alert">{error}</div>}
            <form className={styles.form} onSubmit={handleSubmit(onSubmit)} noValidate>
              <label className="visually-hidden" htmlFor="forgot-email">{t('field.email')}</label>
              <input id="forgot-email" type="email" className="input-field" placeholder={t('field.email')} autoComplete="email" autoFocus {...register('email')} />
              {formState.errors.email && <span className="field-error">{t(formState.errors.email.message)}</span>}
              <Button type="submit" size="lg" fullWidth disabled={formState.isSubmitting} style={{ marginTop: '1.25rem' }}>
                {formState.isSubmitting ? <Spinner size="sm" color="white" /> : t('forgot.submit')}
              </Button>
            </form>
          </>
        )}
        <div className={styles.footer}>
          {t('forgot.remembered')}<Link to="/login">{t('register.signIn')}</Link>.
        </div>
      </section>
    </main>
  );
}
