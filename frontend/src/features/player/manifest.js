import { defineFeature } from '@/core/featureKit';
import { PlayerProvider } from './components/PlayerProvider';

export default defineFeature({
  id: 'player',
  backendModule: 'playback',
  requires: ['auth'],
  providers: [PlayerProvider],
  // player.observers: watchers of an open playback (resume position …)
  // content.actions:  per-card actions on any playable item (favourite toggle …)
  slots: ['player.observers', 'content.actions'],
});
