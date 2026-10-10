import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { CheckCircle2, Clock } from 'lucide-react';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';
import { billingKeys, getSubscription } from '../api';

/** Landing page after the hosted checkout: waits (briefly) for the webhook to activate the plan. */
export default function CheckoutReturnPage() {
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
      <EmptyState icon={CheckCircle2} title="Ödemeniz alındı" action={<Link to="/">İzlemeye başla</Link>}>
        <span style={{ textTransform: 'capitalize' }}>{data.plan}</span> planınız aktif.
      </EmptyState>
    );
  }
  return (
    <EmptyState icon={Clock} title={timedOut ? 'Ödeme henüz onaylanmadı' : 'Ödemeniz onaylanıyor…'} action={<Link to="/plans">Planlara dön</Link>}>
      {timedOut ? 'Onay birkaç dakika sürebilir; planınız aktif olduğunda e-posta ile bilgilendirileceksiniz.' : 'Bu işlem genellikle birkaç saniye sürer.'}
    </EmptyState>
  );
}
