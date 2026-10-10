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

export default function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');
  const { register, handleSubmit, formState } = useForm({ resolver: zodResolver(forgotPasswordSchema) });

  const onSubmit = async ({ email }) => {
    setError('');
    try {
      await api.call('identity_forgot_password', { body: { email } });
      setSent(true);
    } catch (err) {
      setError(err.userMessage ?? 'İstek gönderilemedi.');
    }
  };

  return (
    <main className={styles.screen}>
      <Link to="/login" className={styles.brand}>NeoTV</Link>
      <section className={styles.panel}>
        <h1>Şifremi unuttum</h1>
        {sent ? (
          <div role="status">
            <p className={styles.ok}><MailCheck size={18} aria-hidden="true" /> İsteğiniz alındı.</p>
            <p className={styles.lead}>
              Bu adres bir hesaba kayıtlıysa birkaç dakika içinde şifre sıfırlama bağlantısı gelecek. Bağlantı 30 dakika
              geçerlidir. Gelen kutunuzda yoksa istenmeyen klasörüne bakın.
            </p>
          </div>
        ) : (
          <>
            <p className={styles.lead}>Hesabınıza kayıtlı e-posta adresini girin; size yeni şifre bağlantısı gönderelim.</p>
            {error && <div className={styles.alert} role="alert">{error}</div>}
            <form className={styles.form} onSubmit={handleSubmit(onSubmit)} noValidate>
              <label className="visually-hidden" htmlFor="forgot-email">E-posta</label>
              <input id="forgot-email" type="email" className="input-field" placeholder="E-posta" autoComplete="email" autoFocus {...register('email')} />
              {formState.errors.email && <span className="field-error">{formState.errors.email.message}</span>}
              <Button type="submit" size="lg" fullWidth disabled={formState.isSubmitting} style={{ marginTop: '1.25rem' }}>
                {formState.isSubmitting ? <Spinner size="sm" color="white" /> : 'Bağlantı gönder'}
              </Button>
            </form>
          </>
        )}
        <div className={styles.footer}>
          Şifrenizi hatırladınız mı?<Link to="/login">Oturum açın</Link>.
        </div>
      </section>
    </main>
  );
}
