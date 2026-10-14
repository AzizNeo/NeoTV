import { MonitorSmartphone } from 'lucide-react';
import { defineFeature } from '@/core/featureKit';
import { messages } from './i18n';

export default defineFeature({
  id: 'devices',
  backendModule: 'devices',
  requires: ['auth'],
  routes: [{ path: '/devices', lazy: () => import('./pages/DevicesPage') }],
  nav: [{ to: '/devices', label: messages.ref('nav.devices'), icon: MonitorSmartphone, order: 70, section: 'account' }],
});
