import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Panel } from '@/shared/components/Page/Page';
import { billingKeys, date, getSubscription, statusText } from '../api';
import { useT } from '../i18n';

/** Contributed to `account.sections`. */
export function SubscriptionSummary() {
  const t = useT();
  const { data } = useQuery({ queryKey: billingKeys.subscription, queryFn: getSubscription });
  if (!data) return null;
  const until = data.status === 'trial' ? data.trial_ends_at : data.current_period_end;
  return (
    <Panel title={t('summary.title')} actions={<Link to="/plans">{t('summary.seePlans')}</Link>}>
      <p style={{ margin: 0 }}>
        <strong style={{ textTransform: 'capitalize' }}>{data.effective_plan}</strong> · {statusText(data.status, t)}
        {until ? ` · ${date(until, t)}` : ''}
      </p>
      <p style={{ color: 'var(--color-text-secondary)', marginBottom: 0 }}>
        {[
          t('summary.screens', { count: data.entitlements.max_streams }),
          t('perks.profiles', { count: data.entitlements.max_profiles }),
          t('summary.upTo', { resolution: data.entitlements.max_resolution }),
        ].join(' · ')}
      </p>
    </Panel>
  );
}
