import { Home } from 'lucide-react';
import { defineFeature } from '@/core/featureKit';

export default defineFeature({
  id: 'catalog',
  backendModule: 'catalog',
  requires: ['auth', 'player'],
  routes: [{ path: '/', lazy: () => import('./pages/HomePage') }],
  nav: [{ to: '/', label: 'Ana Sayfa', icon: Home, order: 10 }],
  // Rows on the home screen contributed by other features.
  slots: ['home.rows'],
});
