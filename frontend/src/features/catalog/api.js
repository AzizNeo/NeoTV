import { api } from '@/core/api/client';

export const catalogKeys = {
  groups: ['catalog', 'groups'],
  group: (name, kind) => ['catalog', 'group', name, kind ?? 'all'],
  search: (term, kind) => ['catalog', 'search', term, kind ?? 'all'],
};

export const toCard = (c) => ({ ref: c.ref, title: c.name, image: c.logo ?? null, caption: c.group, live: c.kind === 'live' });

export const fetchGroups = () => api.call('catalog_groups');
export const fetchChannels = ({ group, kind, search, perPage = 24, signal }) =>
  api.call('catalog_list_channels', { query: { group, kind, search, per_page: perPage }, signal });
