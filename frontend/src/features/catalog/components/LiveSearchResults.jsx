import PropTypes from 'prop-types';
import { useQuery } from '@tanstack/react-query';
import { Slot } from '@/core/featureKit';
import { usePlayer } from '@/features/player';
import { ContentRow } from '@/shared/components/ContentRow/ContentRow';
import { catalogKeys, fetchChannels, toCard } from '../api';

/** Contributed to `search.results`: live channels matching the query (films come from the storefront). */
export function LiveSearchResults({ query }) {
  const { play } = usePlayer();
  const { data } = useQuery({
    queryKey: catalogKeys.search(query, 'live'),
    queryFn: ({ signal }) => fetchChannels({ search: query, kind: 'live', perPage: 20, signal }),
  });
  if (!data?.items.length) return null;
  return (
    <ContentRow title="Canlı kanallar" subtitle={`${data.total} kanal`} items={data.items.map(toCard)} onSelect={play}
      actions={(item) => <Slot name="content.actions" item={item} />} />
  );
}
LiveSearchResults.propTypes = { query: PropTypes.string.isRequired };
