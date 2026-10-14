import { Radio } from 'lucide-react';
import { defineFeature } from '@/core/featureKit';
import { messages } from './i18n';
import { LiveChannelResults } from './components/LiveChannelResults';

export default defineFeature({
  id: 'live',
  backendModule: 'live',
  requires: ['auth', 'player'],
  routes: [{ path: '/live', lazy: () => import('./pages/LiveTvPage') }],
  nav: [{ to: '/live', label: messages.ref('nav.live'), icon: Radio, order: 20 }],
  contributes: [{ slot: 'search.results', component: LiveChannelResults, order: 5 }],
});
