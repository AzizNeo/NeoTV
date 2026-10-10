import { defineFeature } from '@/core/featureKit';
import { ProfileBadge } from './components/ProfileBadge';
import { ProfileProvider } from './components/ProfileProvider';

export default defineFeature({
  id: 'profiles',
  backendModule: 'profile',
  requires: ['auth'],
  providers: [ProfileProvider],
  contributes: [{ slot: 'shell.user', component: ProfileBadge }],
  routes: [
    { path: '/profiles', lazy: () => import('./pages/ProfileSelectPage'), layout: 'bare' },
    { path: '/profiles/manage', lazy: () => import('./pages/ProfileManagePage') },
  ],
});
