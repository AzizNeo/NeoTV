import { useQuery } from '@tanstack/react-query';
import { api } from '@/core/api/client';
import { Slot } from '@/core/featureKit';
import { ContentRow } from '@/shared/components/ContentRow/ContentRow';
import { libraryKeys, toCard } from '../api';

/** Contributed to `home.rows`. */
export function ContinueWatchingRow({ onSelect }) {
  const { data } = useQuery({ queryKey: libraryKeys.continue, queryFn: () => api.call('library_continue_watching', { query: { limit: 12 } }) });
  if (!data?.length) return null;
  return (
    <ContentRow
      title="İzlemeye devam et"
      items={data.map((entry) => toCard(entry.content, { progress: entry.progress_percent }))}
      onSelect={onSelect}
      actions={(item) => <Slot name="content.actions" item={item} />}
    />
  );
}
