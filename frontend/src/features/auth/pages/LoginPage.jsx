import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { useAuth } from '@/core/auth/AuthProvider';
import { Button } from '@/shared/components/Button/Button';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { loginSchema } from '../schema';
import { PasswordInput } from './PasswordInput';
import styles from './AuthLayout.module.css';
import { useT } from '../i18n';
import { LanguageSwitch } from '@/core/i18n';

export default function LoginPage() {
  const t = useT();
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [error, setError] = useState('');
  const { register, handleSubmit, formState } = useForm({ resolver: zodResolver(loginSchema) });

  const onSubmit = async ({ username, password }) => {
    setError('');
    try {
      await login(username, password);
      navigate(location.state?.from?.pathname ?? '/', { replace: true });
    } catch (err) {
      setError(err.userMessage ?? t('login.failed'));
    }
  };

  return (
    <main className={styles.screen}>
      <Link to="/login" className={styles.brand}>NeoTV</Link>
      <LanguageSwitch className={styles.lang} />
      <section className={styles.panel}>
        <h1>{t('login.title')}</h1>
        {error && <div className={styles.alert} role="alert">{error}</div>}
        <form className={styles.form} onSubmit={handleSubmit(onSubmit)} noValidate>
          <label className="visually-hidden" htmlFor="login-username">{t('field.username')}</label>
          <input id="login-username" className="input-field" placeholder={t('field.username')} autoComplete="username" autoFocus {...register('username')} />
          {formState.errors.username && <span className="field-error">{t(formState.errors.username.message)}</span>}
          <label className="visually-hidden" htmlFor="login-password">{t('field.password')}</label>
          <PasswordInput id="login-password" placeholder={t('field.password')} autoComplete="current-password" {...register('password')} />
          {formState.errors.password && <span className="field-error">{t(formState.errors.password.message)}</span>}
          <Link to="/forgot-password" className={styles.forgot}>{t('login.forgot')}</Link>
          <Button type="submit" size="lg" fullWidth disabled={formState.isSubmitting} style={{ marginTop: '1.25rem' }}>
            {formState.isSubmitting ? <Spinner size="sm" color="white" /> : t('login.submit')}
          </Button>
        </form>
        <div className={styles.footer}>
          {t('login.newHere')}<Link to="/register">{t('login.signUp')}</Link>.
        </div>
      </section>
    </main>
  );
}
