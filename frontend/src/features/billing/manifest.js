import { Crown } from 'lucide-react';
import { defineFeature } from '@/core/featureKit';
import { SubscriptionSummary } from './components/SubscriptionSummary';

export default defineFeature({
  id: 'billing',
  backendModule: 'billing',
  requires: ['auth'],
  routes: [
    { path: '/plans', lazy: () => import('./pages/PlansPage') },
    { path: '/billing/return', lazy: () => import('./pages/CheckoutReturnPage') },
    { path: '/billing/checkout/fake', lazy: () => import('./pages/FakeCheckoutPage') },
  ],
  nav: [{ to: '/plans', label: 'Premium', icon: Crown, order: 60 }],
  contributes: [{ slot: 'account.sections', component: SubscriptionSummary, order: 10 }],
});
