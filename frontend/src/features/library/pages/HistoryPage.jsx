import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { History, Trash2 } from 'lucide-react';
import { api } from '@/core/api/client';
import { usePlayer } from '@/features/player';
import { Button } from '@/shared/components/Button/Button';
import { ContentRow } from '@/shared/components/ContentRow/ContentRow';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';
import { Page } from '@/shared/components/Page/Page';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { useToast } from '@/shared/components/Toast/Toast';
import { libraryKeys, toCard } from '../api';
import { useFormat } from '@/core/i18n';
import { useT } from '../i18n';

const watched = (s, t) => (s >= 60 ? t('history.minutes', { n: Math.round(s / 60) }) : t('history.seconds', { n: s }));

export default function HistoryPage() {
  const t = useT();
  const { dateTime } = useFormat();
  const { play } = usePlayer();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: libraryKeys.history, queryFn: () => api.call('library_history', { query: { limit: 100 } }) });
  const clear = useMutation({
    mutationFn: () => api.call('library_clear_history'),
    onSuccess: (r) => {
      toast.success(t('history.cleared', { count: r.deleted }));
      queryClient.invalidateQueries({ queryKey: ['library'] });
    },
    onError: (err) => toast.error(err.userMessage),
  });

  if (isLoading) return <Spinner fullScreen />;
  return (
    <Page
      title={t('history.title')}
      actions={data?.length ? <Button variant="secondary" onClick={() => clear.mutate()} disabled={clear.isPending}><Trash2 size={16} style={{ marginRight: 6 }} />{t('history.clear')}</Button> : null}
    >
      {data?.length ? (
        <ContentRow
          layout="grid"
          title={t('history.recent')}
          items={data.map((h) => ({ ...toCard(h.content), ref: h.content.ref, key: h.id, caption: `${dateTime(h.watched_at)} · ${watched(h.watched_seconds, t)}` }))}
          onSelect={play}
        />
      ) : (
        <EmptyState icon={History} title={t('history.empty')}>{t('history.emptyBody')}</EmptyState>
      )}
    </Page>
  );
}
