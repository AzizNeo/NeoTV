import { Tv } from 'lucide-react';
import { defineFeature } from '@/core/featureKit';
import { messages } from './i18n';

// TV apps (Xtream-compatible player API, ADR-0011): app credentials for IPTV apps on TVs and boxes.
export default defineFeature({
  id: 'tv-apps',
  backendModule: 'xtream',
  requires: ['auth', 'profiles'],
  routes: [{ path: '/tv-apps', lazy: () => import('./pages/TvAppsPage') }],
  nav: [{ to: '/tv-apps', label: messages.ref('nav.tvApps'), icon: Tv, order: 75, section: 'account' }],
});
