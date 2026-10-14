/**
 * Admin tabs as data. Adding a back-office area = one entry here + one section
 * file. `module` hides the tab when that backend module is disabled (the
 * backend would answer 404 anyway; hiding avoids a dead tab).
 */
import { lazy } from 'react';
import { messages } from '../i18n';
import { Activity, Ban, Film, KeyRound, LayoutDashboard, Radio, Users } from 'lucide-react';

export const ADMIN_SECTIONS = Object.freeze([
  { id: 'overview', label: messages.ref('sections.overview'), icon: LayoutDashboard, module: 'admin', component: lazy(() => import('./OverviewSection')) },
  { id: 'users', label: messages.ref('sections.users'), icon: Users, module: 'admin', component: lazy(() => import('./UsersSection')) },
  { id: 'sessions', label: messages.ref('sections.sessions'), icon: Activity, module: 'admin', component: lazy(() => import('./SessionsSection')) },
  { id: 'abuse', label: messages.ref('sections.abuse'), icon: Ban, module: 'admin', component: lazy(() => import('./AbuseSection')) },
  { id: 'catalog', label: messages.ref('sections.catalog'), icon: Film, module: 'catalog', component: lazy(() => import('./CatalogSection')) },
  { id: 'live', label: messages.ref('sections.live'), icon: Radio, module: 'live', component: lazy(() => import('./LiveSection')) },
  { id: 'drm', label: messages.ref('sections.drm'), icon: KeyRound, module: 'drm', component: lazy(() => import('./DrmSection')) },
]);

const ids = new Set();
for (const section of ADMIN_SECTIONS) {
  if (ids.has(section.id)) throw new Error(`[feature:admin] duplicate admin section '${section.id}'`);
  ids.add(section.id);
}
