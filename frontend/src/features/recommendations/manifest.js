import { defineFeature } from '@/core/featureKit';
import { RecommendationRows } from './components/RecommendationRows';

export default defineFeature({
  id: 'recommendations',
  backendModule: 'recommendations',
  requires: ['auth'],
  contributes: [{ slot: 'home.rows', component: RecommendationRows, order: 20 }],
});
