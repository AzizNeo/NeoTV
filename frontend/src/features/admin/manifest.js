import { Shield } from 'lucide-react';
import { defineFeature } from '@/core/featureKit';
import { messages } from './i18n';

export default defineFeature({
  id: 'admin',
  backendModule: 'admin',
  requires: ['auth'],
  routes: [{ path: '/admin/*', guard: 'admin', lazy: () => import('./pages/AdminPage') }],
  nav: [{ to: '/admin', label: messages.ref('nav.admin'), icon: Shield, order: 90, guard: 'admin', section: 'account' }],
});
