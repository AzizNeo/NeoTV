import { useQuery } from '@tanstack/react-query';
import { api } from '@/core/api/client';
import { Slot } from '@/core/featureKit';
import { ContentRow } from '@/shared/components/ContentRow/ContentRow';

/** Contributed to `home.rows`: For You, Because you watched …, Trending. */
export function RecommendationRows({ onSelect }) {
  const { data } = useQuery({
    queryKey: ['recommendations', 'home'],
    queryFn: () => api.call('recommendations_home', { query: { limit: 12 } }),
    staleTime: 5 * 60_000,
    retry: false, // optional enhancement: degrade silently (backend may be busy)
  });
  return (data ?? []).map((row) => (
    <ContentRow
      key={row.key}
      title={row.title}
      items={row.items.map((i) => ({ ref: i.ref, title: i.title, image: i.image, live: i.kind === 'live', reason: i.reason, caption: row.key === 'for_you' ? i.reason : i.group ?? undefined }))}
      onSelect={onSelect}
      actions={(item) => <Slot name="content.actions" item={item} />}
    />
  ));
}
