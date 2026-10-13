import { api } from '@/core/api/client';

export const liveKeys = { channels: ['live', 'channels'], guide: ['live', 'guide'] };
export const fetchLiveChannels = ({ signal } = {}) => api.call('live_list_channels', { signal });

const time = (iso) => new Date(iso).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });

/** Live channel → ContentRow card ("now · next" as the caption). One mapping for every live view. */
export const toLiveCard = (c) => ({
  ref: c.ref,
  title: c.name,
  image: c.logo,
  live: c.is_live,
  caption: c.now ? `${time(c.now.starts_at)} ${c.now.title}${c.next ? ` · Sonra: ${c.next.title}` : ''}` : c.description ?? undefined,
});
