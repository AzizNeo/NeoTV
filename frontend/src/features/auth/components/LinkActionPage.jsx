import { useEffect, useEffectEvent, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { CheckCircle2, XCircle } from 'lucide-react';
import { api } from '@/core/api/client';
import { useAuth } from '@/core/auth/AuthProvider';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { useLinkToken } from '../hooks/useLinkToken';
import styles from '../pages/AuthLayout.module.css';
import { useT } from '../i18n';
import { LanguageSwitch } from '@/core/i18n';

/**
 * Page opened from a one-time e-mail link: redeems `#token=…` with `operationId` exactly once.
 *
 * `onDone(auth)` reacts to success (refresh the user, drop a revoked session …); `successText` and
 * `errorHint` are the only per-link copy.
 */
export function LinkActionPage({ operationId, title, successText, errorHint, onDone }) {
  const t = useT();
  const token = useLinkToken();
  const auth = useAuth();
  const [result, setResult] = useState(() => (token ? { status: 'pending' } : { status: 'error', message: null }));
  const started = useRef(false); // the link is single-use: never submit it twice (StrictMode re-runs effects)
  const succeed = useEffectEvent(() => onDone?.(auth)); // latest props, without re-running the effect

  useEffect(() => {
    if (!token || started.current) return;
    started.current = true;
    api
      .call(operationId, { body: { token } })
      .then(() => {
        setResult({ status: 'done' });
        succeed();
      })
      .catch((err) => setResult({ status: 'error', message: err.userMessage }));
  }, [token, operationId]);

  const signedIn = auth.isAuthenticated;
  return (
    <main className={styles.screen}>
      <Link to="/" className={styles.brand}>NeoTV</Link>
      <LanguageSwitch className={styles.lang} />
      <section className={styles.panel} aria-live="polite">
        <h1>{title}</h1>
        {result.status === 'pending' && <Spinner />}
        {result.status === 'done' && (
          <p className={styles.ok}><CheckCircle2 size={18} aria-hidden="true" /> {successText}</p>
        )}
        {result.status === 'error' && (
          <div className={styles.alert} role="alert">
            <XCircle size={16} aria-hidden="true" /> {result.message ?? t('link.broken')} {errorHint}
          </div>
        )}
        <div className={styles.footer}>
          <Link to={signedIn ? '/account' : '/login'}>{t(signedIn ? 'link.backToAccount' : 'link.signIn')}</Link>
        </div>
      </section>
    </main>
  );
}
