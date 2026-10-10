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

/** Collects exactly what the backend stores (FE-06): username, optional e-mail, password. */
export default function RegisterPage() {
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
      setError(err.userMessage ?? 'Kayıt başarısız.');
    }
  };

  return (
    <main className={styles.screen}>
      <Link to="/login" className={styles.brand}>NeoTV</Link>
      <section className={styles.panel}>
        <h1>Hesap Oluştur</h1>
        {error && <div className={styles.alert} role="alert">{error}</div>}
        <form className={styles.form} onSubmit={handleSubmit(onSubmit)} noValidate>
          <input className="input-field" placeholder="Kullanıcı adı" autoComplete="username" aria-label="Kullanıcı adı" {...register('username')} />
          {formState.errors.username ? (
            <span className="field-error">{formState.errors.username.message}</span>
          ) : availability === false ? (
            <span className="field-error">Bu kullanıcı adı alınmış.</span>
          ) : availability === true ? (
            <span className={styles.ok}>Kullanıcı adı uygun.</span>
          ) : null}
          <input className="input-field" placeholder="E-posta (isteğe bağlı)" type="email" autoComplete="email" aria-label="E-posta" {...register('email')} />
          {formState.errors.email && <span className="field-error">{formState.errors.email.message}</span>}
          <PasswordInput placeholder="Şifre" autoComplete="new-password" aria-label="Şifre" {...register('password')} />
          {formState.errors.password ? (
            <span className="field-error">{formState.errors.password.message}</span>
          ) : (
            <p className={styles.hint}>En az 10 karakter; harf, rakam veya simgeden en az ikisi.</p>
          )}
          <PasswordInput placeholder="Şifre (tekrar)" autoComplete="new-password" aria-label="Şifre tekrar" {...register('confirm')} />
          {formState.errors.confirm && <span className="field-error">{formState.errors.confirm.message}</span>}
          <Button type="submit" size="lg" fullWidth disabled={formState.isSubmitting || availability === false} style={{ marginTop: '1.25rem' }}>
            {formState.isSubmitting ? <Spinner size="sm" color="white" /> : 'Kaydol'}
          </Button>
        </form>
        <div className={styles.footer}>
          Zaten hesabınız var mı?<Link to="/login">Oturum açın</Link>.
        </div>
      </section>
    </main>
  );
}
