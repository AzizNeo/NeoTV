import { Home } from 'lucide-react';
import { defineFeature } from '@/core/featureKit';
import { messages } from './i18n';
import { LiveSearchResults } from './components/LiveSearchResults';

export default defineFeature({
  id: 'catalog',
  backendModule: 'catalog',
  requires: ['auth', 'player'],
  routes: [{ path: '/', lazy: () => import('./pages/HomePage') }],
  nav: [{ to: '/', label: messages.ref('nav.home'), icon: Home, order: 10 }],
  // The home screen is composed from contributions: a billboard and rows (continue watching, titles …).
  slots: ['home.hero', 'home.rows'],
  // Dropped automatically if the storefront (which owns search) is off.
  contributes: [{ slot: 'search.results', component: LiveSearchResults, order: 10 }],
});
