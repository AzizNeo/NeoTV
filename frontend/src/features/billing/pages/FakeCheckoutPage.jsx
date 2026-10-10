import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { CreditCard } from 'lucide-react';
import { api } from '@/core/api/client';
import { Button } from '@/shared/components/Button/Button';
import { Page, Panel } from '@/shared/components/Page/Page';
import { useToast } from '@/shared/components/Toast/Toast';

/**
 * Development payment simulator for PAYMENT_PROVIDER=fake. "Pay" asks the
 * backend to emit a correctly *signed* webhook, so the production webhook path
 * is what actually activates the plan. The backend refuses this outside dev/test.
 */
export default function FakeCheckoutPage() {
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
      toast.success('Ödeme alındı, planınız aktif.');
      navigate('/plans', { replace: true });
    } catch (err) {
      toast.error(err.userMessage);
      setBusy(false);
    }
  };

  return (
    <Page title="Test ödemesi" width="narrow" subtitle="Geliştirme ortamı — gerçek bir ödeme alınmaz.">
      <Panel title={`Plan: ${plan ?? '—'}`}>
        <p style={{ color: 'var(--color-text-secondary)' }}>Oturum: <code>{session}</code></p>
        <div style={{ display: 'flex', gap: '0.5rem' }}>
          <Button onClick={pay} disabled={!session || busy}><CreditCard size={16} style={{ marginRight: 6 }} />Ödemeyi tamamla</Button>
          <Button variant="secondary" onClick={() => navigate('/plans')}>Vazgeç</Button>
        </div>
      </Panel>
    </Page>
  );
}
