import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, XCircle } from 'lucide-react';
import { api } from '@/core/api/client';
import { useAuth } from '@/core/auth/AuthProvider';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { useLinkToken } from '../hooks/useLinkToken';
import styles from './AuthLayout.module.css';

export default function VerifyEmailPage() {
  const token = useLinkToken();
  const { isAuthenticated, reloadUser } = useAuth();
  const [result, setResult] = useState(() => (token ? { status: 'pending' } : { status: 'error', message: null }));
  const started = useRef(false); // the link is single-use: never submit it twice (StrictMode re-runs effects)

  useEffect(() => {
    if (!token || started.current) return;
    started.current = true;
    api
      .call('identity_verify_email', { body: { token } })
      .then(() => {
        setResult({ status: 'done' });
        if (isAuthenticated) reloadUser().catch(() => {});
      })
      .catch((err) => setResult({ status: 'error', message: err.userMessage }));
  }, [token, isAuthenticated, reloadUser]);

  return (
    <main className={styles.screen}>
      <Link to="/" className={styles.brand}>NeoTV</Link>
      <section className={styles.panel} aria-live="polite">
        <h1>E-posta doğrulama</h1>
        {result.status === 'pending' && <Spinner />}
        {result.status === 'done' && (
          <p className={styles.ok}><CheckCircle2 size={18} aria-hidden="true" /> E-posta adresiniz doğrulandı.</p>
        )}
        {result.status === 'error' && (
          <div className={styles.alert} role="alert">
            <XCircle size={16} aria-hidden="true" /> {result.message ?? 'Bağlantı eksik ya da bozuk.'} Hesap sayfanızdan yeni
            bir doğrulama bağlantısı isteyebilirsiniz.
          </div>
        )}
        <div className={styles.footer}>
          <Link to={isAuthenticated ? '/account' : '/login'}>{isAuthenticated ? 'Hesabıma dön' : 'Oturum aç'}</Link>
        </div>
      </section>
    </main>
  );
}
