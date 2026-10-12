import { useQuery } from '@tanstack/react-query';
import { api } from '@/core/api/client';
import { libraryKeys } from '../api';

const EMPTY = new Map();

/**
 * Resume state for many items in one request (episode lists, detail pages): `Map<ref, progress>`.
 * Items without progress are absent. `enabled: false` (library off) → an empty map, no request.
 */
export function useProgressMap(refs, { enabled = true } = {}) {
  const key = [...new Set(refs.filter(Boolean))].sort();
  const { data } = useQuery({
    queryKey: [...libraryKeys.progress, key.join(',')],
    queryFn: ({ signal }) => api.call('library_get_progress_many', { query: { refs: key.join(',') }, signal }),
    enabled: enabled && key.length > 0,
    select: (rows) => new Map(rows.map((p) => [p.content_ref, p])),
  });
  return data ?? EMPTY;
}
