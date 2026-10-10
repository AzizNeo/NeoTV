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

export default function ResetPasswordPage() {
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
      toast.success('Şifreniz güncellendi. Yeni şifrenizle oturum açın.');
      navigate('/login', { replace: true });
    } catch (err) {
      setError(err.userMessage ?? 'Şifre güncellenemedi.');
    }
  };

  return (
    <main className={styles.screen}>
      <Link to="/login" className={styles.brand}>NeoTV</Link>
      <section className={styles.panel}>
        <h1>Yeni şifre belirle</h1>
        {!token ? (
          <div className={styles.alert} role="alert">
            Bağlantı eksik ya da bozuk. <Link to="/forgot-password">Yeni bir bağlantı isteyin</Link>.
          </div>
        ) : (
          <>
            {error && (
              <div className={styles.alert} role="alert">
                {error} <Link to="/forgot-password">Yeni bağlantı iste</Link>
              </div>
            )}
            <form className={styles.form} onSubmit={handleSubmit(onSubmit)} noValidate>
              <PasswordInput placeholder="Yeni şifre" autoComplete="new-password" aria-label="Yeni şifre" autoFocus {...register('password')} />
              {formState.errors.password && <span className="field-error">{formState.errors.password.message}</span>}
              <PasswordInput placeholder="Yeni şifre (tekrar)" autoComplete="new-password" aria-label="Yeni şifre tekrar" {...register('confirm')} />
              {formState.errors.confirm && <span className="field-error">{formState.errors.confirm.message}</span>}
              <p className={styles.lead}>Şifre değişince tüm cihazlardaki oturumlar kapatılır.</p>
              <Button type="submit" size="lg" fullWidth disabled={formState.isSubmitting} style={{ marginTop: '0.5rem' }}>
                {formState.isSubmitting ? <Spinner size="sm" color="white" /> : 'Şifreyi güncelle'}
              </Button>
            </form>
          </>
        )}
      </section>
    </main>
  );
}
