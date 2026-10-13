import PropTypes from 'prop-types';
import { useQuery } from '@tanstack/react-query';
import { Slot } from '@/core/featureKit';
import { usePlayer } from '@/features/player';
import { ContentRow } from '@/shared/components/ContentRow/ContentRow';
import { fetchLiveChannels, liveKeys, toLiveCard } from '../api';

const norm = (s) => s.toLocaleLowerCase('tr');

/**
 * Contributed to `search.results`: matching live channels. The channel list is small and already
 * cached by Live TV (same query key), so it is filtered here instead of adding a search endpoint.
 */
export function LiveChannelResults({ query }) {
  const { play } = usePlayer();
  const { data } = useQuery({ queryKey: liveKeys.channels, queryFn: fetchLiveChannels, staleTime: 60_000 });
  const needle = norm(query.trim());
  const hits = (data ?? []).filter((c) => norm(c.name).includes(needle) || norm(c.now?.title ?? '').includes(needle));
  if (!hits.length) return null;
  return (
    <ContentRow title="Canlı yayınlar" subtitle={`${hits.length} kanal`} items={hits.map(toLiveCard)} onSelect={play}
      actions={(item) => <Slot name="content.actions" item={item} />} />
  );
}
LiveChannelResults.propTypes = { query: PropTypes.string.isRequired };
