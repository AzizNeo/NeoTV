import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Panel } from '@/shared/components/Page/Page';
import { STATUS_TEXT, billingKeys, date, getSubscription } from '../api';

/** Contributed to `account.sections`. */
export function SubscriptionSummary() {
  const { data } = useQuery({ queryKey: billingKeys.subscription, queryFn: getSubscription });
  if (!data) return null;
  const until = data.status === 'trial' ? data.trial_ends_at : data.current_period_end;
  return (
    <Panel title="Abonelik" actions={<Link to="/plans">Planları gör</Link>}>
      <p style={{ margin: 0 }}>
        <strong style={{ textTransform: 'capitalize' }}>{data.effective_plan}</strong> · {STATUS_TEXT[data.status] ?? data.status}
        {until ? ` · ${date(until)}` : ''}
      </p>
      <p style={{ color: 'var(--color-text-secondary)', marginBottom: 0 }}>
        {data.entitlements.max_streams} eşzamanlı ekran · {data.entitlements.max_profiles} profil · en fazla {data.entitlements.max_resolution}
      </p>
    </Panel>
  );
}
