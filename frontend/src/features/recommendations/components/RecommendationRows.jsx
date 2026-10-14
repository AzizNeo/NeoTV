import { useQuery } from '@tanstack/react-query';
import { api } from '@/core/api/client';
import { Slot } from '@/core/featureKit';
import { ContentRow } from '@/shared/components/ContentRow/ContentRow';
import { useT } from '../i18n';

/**
 * Rows and reasons arrive as codes (+ subject): the words are ours, in the viewer's language.
 * An unknown code (a newer backend) falls back to the server's English text.
 */
function rowTitle(row, t) {
  if (row.key === 'for_you') return t('rows.forYou');
  if (row.key === 'trending') return t('rows.trending');
  if (row.key.startsWith('because:') && row.subject) return t('rows.because', { title: row.subject });
  return row.title;
}

const REASONS = new Set(['trending', 'recommended', 'likes_group', 'watched']);
const reasonText = (item, t) => (REASONS.has(item.reason_code) ? t(`reasons.${item.reason_code}`, { subject: item.reason_subject ?? '' }) : item.reason);

/** Contributed to `home.rows`: For You, Because you watched …, Trending. */
export function RecommendationRows({ onSelect }) {
  const t = useT();
  const { data } = useQuery({
    queryKey: ['recommendations', 'home'],
    queryFn: () => api.call('recommendations_home', { query: { limit: 12 } }),
    staleTime: 5 * 60_000,
    retry: false, // optional enhancement: degrade silently (backend may be busy)
  });
  return (data ?? []).map((row) => (
    <ContentRow
      key={row.key}
      title={rowTitle(row, t)}
      items={row.items.map((i) => {
        const reason = reasonText(i, t);
        return { ref: i.ref, title: i.title, image: i.image, live: i.kind === 'live', reason, caption: row.key === 'for_you' ? reason : (i.group ?? undefined) };
      })}
      onSelect={onSelect}
      actions={(item) => <Slot name="content.actions" item={item} />}
    />
  ));
}
