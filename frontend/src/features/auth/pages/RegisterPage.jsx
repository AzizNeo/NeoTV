import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useForm, useWatch } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { api } from '@/core/api/client';
import { useAuth } from '@/core/auth/AuthProvider';
import { Button } from '@/shared/components/Button/Button';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { registerSchema } from '../schema';
import { PasswordInput } from './PasswordInput';
import styles from './AuthLayout.module.css';
import { useT } from '../i18n';
import { LanguageSwitch } from '@/core/i18n';

/** Collects exactly what the backend stores (FE-06): username, optional e-mail, password. */
export default function RegisterPage() {
  const t = useT();
  const { register: signUp } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState('');
  // Result is tagged with the username it answers, so a stale answer never shows for new input.
  const [check, setCheck] = useState({ name: null, available: null });
  const { register, handleSubmit, control, formState } = useForm({
    resolver: zodResolver(registerSchema),
    defaultValues: { username: '', email: '', password: '', confirm: '' },
  });
  const username = useWatch({ control, name: 'username' });
  const availability = check.name === username ? check.available : null;

  useEffect(() => {
    if (!/^[A-Za-z0-9_.-]{3,64}$/.test(username ?? '')) return undefined;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      api
        .call('identity_check_username', { body: { username }, signal: controller.signal })
        .then((r) => setCheck({ name: username, available: r.available }))
        .catch(() => {}); // rate-limited or offline: the submit will tell
    }, 450);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [username]);

  const onSubmit = async (values) => {
    setError('');
    try {
      await signUp(values);
      navigate('/', { replace: true });
    } catch (err) {
      setError(err.userMessage ?? t('register.failed'));
    }
  };

  return (
    <main className={styles.screen}>
      <Link to="/login" className={styles.brand}>NeoTV</Link>
      <LanguageSwitch className={styles.lang} />
      <section className={styles.panel}>
        <h1>{t('register.title')}</h1>
        {error && <div className={styles.alert} role="alert">{error}</div>}
        <form className={styles.form} onSubmit={handleSubmit(onSubmit)} noValidate>
          <input className="input-field" placeholder={t('field.username')} autoComplete="username" aria-label={t('field.username')} {...register('username')} />
          {formState.errors.username ? (
            <span className="field-error">{t(formState.errors.username.message)}</span>
          ) : availability === false ? (
            <span className="field-error">{t('register.taken')}</span>
          ) : availability === true ? (
            <span className={styles.ok}>{t('register.available')}</span>
          ) : null}
          <input className="input-field" placeholder={t('field.emailOptional')} type="email" autoComplete="email" aria-label={t('field.email')} {...register('email')} />
          {formState.errors.email && <span className="field-error">{t(formState.errors.email.message)}</span>}
          <PasswordInput placeholder={t('field.password')} autoComplete="new-password" aria-label={t('field.password')} {...register('password')} />
          {formState.errors.password ? (
            <span className="field-error">{t(formState.errors.password.message)}</span>
          ) : (
            <p className={styles.hint}>{t('register.hint')}</p>
          )}
          <PasswordInput placeholder={t('field.passwordAgain')} autoComplete="new-password" aria-label={t('field.passwordAgain')} {...register('confirm')} />
          {formState.errors.confirm && <span className="field-error">{t(formState.errors.confirm.message)}</span>}
          <Button type="submit" size="lg" fullWidth disabled={formState.isSubmitting || availability === false} style={{ marginTop: '1.25rem' }}>
            {formState.isSubmitting ? <Spinner size="sm" color="white" /> : t('register.submit')}
          </Button>
        </form>
        <div className={styles.footer}>
          {t('register.haveAccount')}<Link to="/login">{t('register.signIn')}</Link>.
        </div>
      </section>
    </main>
  );
}
