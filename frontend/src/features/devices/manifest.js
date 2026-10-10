import { MonitorSmartphone } from 'lucide-react';
import { defineFeature } from '@/core/featureKit';

export default defineFeature({
  id: 'devices',
  backendModule: 'devices',
  requires: ['auth'],
  routes: [{ path: '/devices', lazy: () => import('./pages/DevicesPage') }],
  nav: [{ to: '/devices', label: 'Cihazlar', icon: MonitorSmartphone, order: 70, section: 'account' }],
});
