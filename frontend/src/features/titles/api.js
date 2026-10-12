import { api } from '@/core/api/client';

export const titleKeys = {
  all: ['titles'],
  featured: ['titles', 'featured'],
  rails: ['titles', 'rails'],
  genres: ['titles', 'genres'],
  detail: (slug) => ['titles', 'detail', slug],
  browse: (query) => ['titles', 'browse', query],
};

export const fetchFeatured = ({ signal } = {}) => api.call('titles_featured', { query: { limit: 5 }, signal });
export const fetchRails = ({ signal } = {}) => api.call('titles_rails', { query: { genres: 6, per_rail: 14 }, signal });
export const fetchTitle = (slug, { signal } = {}) => api.call('titles_detail', { params: { slug }, signal });
