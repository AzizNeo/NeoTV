/**
 * The installed features — the frontend twin of backend INSTALLED_MODULES.
 * Order is irrelevant (dependencies are validated by buildRegistry); adding a
 * feature = one import + one array entry. Removing one is the reverse, and any
 * feature still requiring it fails at startup with MissingFeatureError.
 */
import admin from './admin/manifest';
import auth from './auth/manifest';
import billing from './billing/manifest';
import catalog from './catalog/manifest';
import devices from './devices/manifest';
import library from './library/manifest';
import live from './live/manifest';
import player from './player/manifest';
import profiles from './profiles/manifest';
import recommendations from './recommendations/manifest';

export const FEATURES = Object.freeze([
  auth, profiles, player, catalog, live, library, recommendations, billing, devices, admin,
]);
