import { api } from '@/core/api/client';
import { formatTime } from '@/core/i18n';

export const liveKeys = { channels: ['live', 'channels'], guide: ['live', 'guide'] };
export const fetchLiveChannels = ({ signal } = {}) => api.call('live_list_channels', { signal });

/**
 * Live channel → ContentRow card ("now · next" as the caption). One mapping for every live view.
 * `t` is the live translator; times are formatted in the viewer's language.
 */
export const toLiveCard = (c, t) => ({
  ref: c.ref,
  title: c.name,
  image: c.logo,
  live: c.is_live,
  caption: c.now
    ? t(c.next ? 'nowNext' : 'now', { time: formatTime(c.now.starts_at, t.locale), now: c.now.title, next: c.next?.title })
    : (c.description ?? undefined),
});
