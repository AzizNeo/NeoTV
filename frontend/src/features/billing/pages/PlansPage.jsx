import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Crown } from 'lucide-react';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';
import { Modal } from '@/shared/components/Modal/Modal';
import { Page } from '@/shared/components/Page/Page';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { useToast } from '@/shared/components/Toast/Toast';
import { billingKeys, date, getPlans, getSubscription, money, perks, statusText } from '../api';
import styles from './PlansPage.module.css';
import { useT } from '../i18n';

const ACCENT = { free: '#999', personal: '#3498db', duo: '#9b59b6', family: 'var(--color-primary)' };

export default function PlansPage() {
  const t = useT();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [confirmCancel, setConfirmCancel] = useState(false);
  const plans = useQuery({ queryKey: billingKeys.plans, queryFn: getPlans, staleTime: 3_600_000 });
  const sub = useQuery({ queryKey: billingKeys.subscription, queryFn: getSubscription });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['billing'] });
  const onError = (err) => toast.error(err.userMessage);

  const checkout = useMutation({
    mutationFn: (plan) => api.call('billing_checkout', { body: { plan } }),
    onSuccess: (c) => window.location.assign(c.redirect_url), // hosted payment page (or the dev simulator)
    onError,
  });
  const trial = useMutation({
    mutationFn: () => api.call('billing_trial'),
    onSuccess: () => { toast.success(t('plans.trialStarted')); refresh(); },
    onError,
  });
  const cancel = useMutation({
    mutationFn: () => api.call('billing_cancel'),
    onSuccess: () => { setConfirmCancel(false); toast.info(t('plans.cancelled')); refresh(); },
    onError,
  });
  const resume = useMutation({
    mutationFn: () => api.call('billing_resume'),
    onSuccess: () => { toast.success(t('plans.resumed')); refresh(); },
    onError,
  });

  if (plans.isLoading || sub.isLoading) return <Spinner fullScreen />;
  if (plans.isError || sub.isError) {
    return <EmptyState tone="error" title={t('plans.loadFailed')} action={<Button onClick={refresh}>{t('plans.retry')}</Button>} />;
  }
  const current = sub.data;
  const until = current.status === 'trial' ? current.trial_ends_at : current.current_period_end;

  return (
    <Page title={t('plans.title')} subtitle={t('plans.subtitle')}>
      <div className={styles.status}>
        <Crown size={18} aria-hidden="true" />
        <span>
          {t('plans.currentLine')} <strong>{current.effective_plan}</strong> — {statusText(current.status, t)}
          {until ? ` · ${date(until, t)}` : ''}
        </span>
        {current.trial_available && (
          <Button size="sm" variant="secondary" onClick={() => trial.mutate()} disabled={trial.isPending}>
            {t('plans.tryFree')}
          </Button>
        )}
      </div>

      <div className={styles.grid}>
        {plans.data.map((plan) => {
          const isCurrent = current.plan === plan.id && current.status !== 'expired';
          const accent = ACCENT[plan.id] ?? '#aaa';
          return (
            <article key={plan.id} className={`${styles.card} ${isCurrent ? styles.current : ''}`} style={{ '--accent': accent }}>
              {isCurrent && <span className={styles.badge}><Check size={14} /> {t('plans.current')}</span>}
              <h2 style={{ color: accent }}>{plan.display_name}</h2>
              <div className={styles.price}>
                {money(plan.price_minor, plan.currency, t)}
                {plan.price_minor > 0 && <small>{t('perMonth')}</small>}
              </div>
              <ul>
                {perks(plan.entitlements, t).map((f) => (
                  <li key={f}><Check size={18} color={accent} aria-hidden="true" /> {f}</li>
                ))}
              </ul>
              {plan.price_minor > 0 && (
                <button className={styles.choose} disabled={isCurrent || checkout.isPending} onClick={() => checkout.mutate(plan.id)}>
                  {isCurrent ? t('plans.active') : t('plans.choose', { plan: plan.display_name })}
                </button>
              )}
            </article>
          );
        })}
      </div>

      {current.plan !== 'free' && (
        <div className={styles.manage}>
          {current.status === 'cancelled' ? (
            <Button onClick={() => resume.mutate()} disabled={resume.isPending}>{t('plans.resume')}</Button>
          ) : (
            <button className={styles.cancelLink} onClick={() => setConfirmCancel(true)}>{t('plans.cancel')}</button>
          )}
        </div>
      )}

      <Modal isOpen={confirmCancel} onClose={() => setConfirmCancel(false)} title={t('plans.cancel')}>
        <p>{t('plans.cancelBody', { date: date(until, t) ?? '—' })}</p>
        <div style={{ display: 'flex', gap: '0.5rem', justifyContent: 'flex-end' }}>
          <Button variant="secondary" onClick={() => setConfirmCancel(false)}>{t('plans.keep')}</Button>
          <Button variant="danger" onClick={() => cancel.mutate()} disabled={cancel.isPending}>{t('plans.confirmCancel')}</Button>
        </div>
      </Modal>
    </Page>
  );
}
