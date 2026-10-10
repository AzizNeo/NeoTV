import { Shield } from 'lucide-react';
import { defineFeature } from '@/core/featureKit';

export default defineFeature({
  id: 'admin',
  backendModule: 'admin',
  requires: ['auth'],
  routes: [{ path: '/admin/*', guard: 'admin', lazy: () => import('./pages/AdminPage') }],
  nav: [{ to: '/admin', label: 'Yönetim', icon: Shield, order: 90, guard: 'admin', section: 'account' }],
});
