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

export default function LoginPage() {
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
      setError(err.userMessage ?? 'Giriş başarısız.');
    }
  };

  return (
    <main className={styles.screen}>
      <Link to="/login" className={styles.brand}>NeoTV</Link>
      <section className={styles.panel}>
        <h1>Oturum Aç</h1>
        {error && <div className={styles.alert} role="alert">{error}</div>}
        <form className={styles.form} onSubmit={handleSubmit(onSubmit)} noValidate>
          <label className="visually-hidden" htmlFor="login-username">Kullanıcı adı</label>
          <input id="login-username" className="input-field" placeholder="Kullanıcı adı" autoComplete="username" autoFocus {...register('username')} />
          {formState.errors.username && <span className="field-error">{formState.errors.username.message}</span>}
          <label className="visually-hidden" htmlFor="login-password">Şifre</label>
          <PasswordInput id="login-password" placeholder="Şifre" autoComplete="current-password" {...register('password')} />
          {formState.errors.password && <span className="field-error">{formState.errors.password.message}</span>}
          <Link to="/forgot-password" className={styles.forgot}>Şifremi unuttum</Link>
          <Button type="submit" size="lg" fullWidth disabled={formState.isSubmitting} style={{ marginTop: '1.25rem' }}>
            {formState.isSubmitting ? <Spinner size="sm" color="white" /> : 'Oturum Aç'}
          </Button>
        </form>
        <div className={styles.footer}>
          NeoTV&apos;de yeni misiniz?<Link to="/register">Hemen kaydolun</Link>.
        </div>
      </section>
    </main>
  );
}
