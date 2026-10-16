import { Shield } from 'lucide-react';
import { defineFeature } from '@/core/featureKit';
import { messages } from './i18n';
import { ADMIN_BASE } from './paths';

export default defineFeature({
  id: 'admin',
  backendModule: 'admin',
  requires: ['auth'],
  routes: [{ path: `${ADMIN_BASE}/*`, guard: 'admin', lazy: () => import('./pages/AdminPage') }],
  nav: [{ to: ADMIN_BASE, label: messages.ref('nav.admin'), icon: Shield, order: 90, guard: 'admin', section: 'account' }],
});
