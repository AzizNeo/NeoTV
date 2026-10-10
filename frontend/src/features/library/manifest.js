import { Heart, History } from 'lucide-react';
import { defineFeature } from '@/core/featureKit';
import { ContinueWatchingRow } from './components/ContinueWatchingRow';
import { FavoriteToggle } from './components/FavoriteToggle';
import { ProgressTracker } from './components/ProgressTracker';

export default defineFeature({
  id: 'library',
  backendModule: 'library',
  requires: ['auth', 'player'],
  routes: [
    { path: '/favorites', lazy: () => import('./pages/FavoritesPage') },
    { path: '/history', lazy: () => import('./pages/HistoryPage') },
  ],
  nav: [
    { to: '/favorites', label: 'Favoriler', icon: Heart, order: 30 },
    { to: '/history', label: 'Geçmiş', icon: History, order: 40 },
  ],
  contributes: [
    { slot: 'home.rows', component: ContinueWatchingRow, order: 10 },
    { slot: 'content.actions', component: FavoriteToggle, order: 10 },
    { slot: 'player.observers', component: ProgressTracker, order: 10 },
  ],
});
