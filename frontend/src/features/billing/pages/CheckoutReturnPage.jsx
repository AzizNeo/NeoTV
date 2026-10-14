import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { CheckCircle2, Clock } from 'lucide-react';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';
import { billingKeys, getSubscription } from '../api';
import { useT } from '../i18n';

/** Landing page after the hosted checkout: waits (briefly) for the webhook to activate the plan. */
export default function CheckoutReturnPage() {
  const t = useT();
  const [deadline] = useState(() => Date.now() + 30_000);
  const { data } = useQuery({
    queryKey: billingKeys.subscription,
    queryFn: getSubscription,
    refetchInterval: (query) => (query.state.data?.status === 'active' || Date.now() > deadline ? false : 2000),
  });
  const [timedOut, setTimedOut] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setTimedOut(true), 30_000);
    return () => clearTimeout(t);
  }, []);

  if (data?.status === 'active' && data.plan !== 'free') {
    return (
      <EmptyState icon={CheckCircle2} title={t('checkout.paid')} action={<Link to="/">{t('checkout.start')}</Link>}>
        {t('checkout.planActive', { plan: data.plan.charAt(0).toLocaleUpperCase(t.locale) + data.plan.slice(1) })}
      </EmptyState>
    );
  }
  return (
    <EmptyState icon={Clock} title={t(timedOut ? 'checkout.late' : 'checkout.pending')} action={<Link to="/plans">{t('checkout.back')}</Link>}>
      {t(timedOut ? 'checkout.lateBody' : 'checkout.pendingBody')}
    </EmptyState>
  );
}
