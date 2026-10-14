import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { CreditCard } from 'lucide-react';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { Page, Panel } from '@/shared/components/Page/Page';
import { useToast } from '@/shared/components/Toast/Toast';
import { useT } from '../i18n';

/**
 * Development payment simulator for PAYMENT_PROVIDER=fake. "Pay" asks the
 * backend to emit a correctly *signed* webhook, so the production webhook path
 * is what actually activates the plan. The backend refuses this outside dev/test.
 */
export default function FakeCheckoutPage() {
  const t = useT();
  const [params] = useSearchParams();
  const session = params.get('session');
  const plan = params.get('plan');
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);

  const pay = async () => {
    setBusy(true);
    try {
      await api.call('billing_dev_complete_checkout', { params: { checkout_id: session } });
      await queryClient.invalidateQueries({ queryKey: ['billing'] });
      toast.success(t('fake.done'));
      navigate('/plans', { replace: true });
    } catch (err) {
      toast.error(err.userMessage);
      setBusy(false);
    }
  };

  return (
    <Page title={t('fake.title')} width="narrow" subtitle={t('fake.subtitle')}>
      <Panel title={t('fake.plan', { plan: plan ?? '—' })}>
        <p style={{ color: 'var(--color-text-secondary)' }}>{t('fake.session')} <code>{session}</code></p>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <Button onClick={pay} disabled={!session || busy}><CreditCard size={16} style={{ marginRight: 6 }} />{t('fake.pay')}</Button>
          <Button variant="secondary" onClick={() => navigate('/plans')}>{t('fake.back')}</Button>
        </div>
      </Panel>
    </Page>
  );
}
