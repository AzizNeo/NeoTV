import { defineFeature } from '@/core/featureKit';
import { HeroBillboard } from './components/HeroBillboard';
import { TitleRails } from './components/TitleRails';

/**
 * Storefront (movies & series) over the backend `titles` module. Everything here plugs into
 * slots owned by `catalog`, so with the module off the home page simply shows channel groups.
 */
export default defineFeature({
  id: 'titles',
  backendModule: 'titles',
  requires: ['auth', 'player', 'catalog'],
  routes: [{ path: '/title/:slug', lazy: () => import('./pages/TitleDetailPage') }],
  contributes: [
    { slot: 'home.hero', component: HeroBillboard, order: 10 },
    { slot: 'home.rows', component: TitleRails, order: 15 },
  ],
});
