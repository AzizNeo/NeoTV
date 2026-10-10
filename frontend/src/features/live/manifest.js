import { Radio } from 'lucide-react';
import { defineFeature } from '@/core/featureKit';

export default defineFeature({
  id: 'live',
  backendModule: 'live',
  requires: ['auth', 'player'],
  routes: [{ path: '/live', lazy: () => import('./pages/LiveTvPage') }],
  nav: [{ to: '/live', label: 'Canlı TV', icon: Radio, order: 20 }],
});
