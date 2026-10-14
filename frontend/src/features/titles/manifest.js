import { Clapperboard } from 'lucide-react';
import { defineFeature } from '@/core/featureKit';
import { messages } from './i18n';
import { HeroBillboard } from './components/HeroBillboard';
import { SearchAction } from './components/SearchAction';
import { TitleRails } from './components/TitleRails';

/**
 * Storefront (movies & series) over the backend `titles` module. Everything here plugs into
 * slots owned by `catalog`, so with the module off the home page simply shows channel groups.
 */
export default defineFeature({
  id: 'titles',
  backendModule: 'titles',
  requires: ['auth', 'player', 'catalog', 'profiles'],
  routes: [
    { path: '/browse', lazy: () => import('./pages/BrowsePage') },
    { path: '/title/:slug', lazy: () => import('./pages/TitleDetailPage') },
  ],
  nav: [{ to: '/browse', label: messages.ref('nav.browse'), icon: Clapperboard, order: 15 }],
  // Other features add their own matches to a search (live channels from catalog …).
  slots: ['search.results'],
  contributes: [
    { slot: 'home.hero', component: HeroBillboard, order: 10 },
    { slot: 'home.rows', component: TitleRails, order: 15 },
    { slot: 'shell.actions', component: SearchAction, order: 10 },
  ],
});
