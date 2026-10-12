import { api } from '@/core/api/client';

export const libraryKeys = {
  favoriteRefs: ['library', 'favorite-refs'],
  favorites: ['library', 'favorites'],
  continue: ['library', 'continue'],
  history: ['library', 'history'],
  progress: ['library', 'progress'],
};

export const toCard = (content, extra = {}) => ({
  ref: content.ref,
  title: content.title,
  image: content.image,
  caption: content.group ?? undefined,
  live: content.kind === 'live',
  ...extra,
});

export const getFavoriteRefs = () => api.call('library_favorite_refs');
export const setFavorite = (ref, on) =>
  api.call(on ? 'library_add_favorite' : 'library_remove_favorite', { params: { content_ref: ref } });
