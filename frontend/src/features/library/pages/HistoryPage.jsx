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

const when = (iso) => new Date(iso).toLocaleString('tr-TR', { dateStyle: 'medium', timeStyle: 'short' });
const minutes = (s) => (s >= 60 ? `${Math.round(s / 60)} dk` : `${s} sn`);

export default function HistoryPage() {
  const { play } = usePlayer();
  const toast = useToast();
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: libraryKeys.history, queryFn: () => api.call('library_history', { query: { limit: 100 } }) });
  const clear = useMutation({
    mutationFn: () => api.call('library_clear_history'),
    onSuccess: (r) => {
      toast.success(`${r.deleted} kayıt silindi.`);
      queryClient.invalidateQueries({ queryKey: ['library'] });
    },
    onError: (err) => toast.error(err.userMessage),
  });

  if (isLoading) return <Spinner fullScreen />;
  return (
    <Page
      title="İzleme geçmişi"
      actions={data?.length ? <Button variant="secondary" onClick={() => clear.mutate()} disabled={clear.isPending}><Trash2 size={16} style={{ marginRight: 6 }} />Geçmişi temizle</Button> : null}
    >
      {data?.length ? (
        <ContentRow
          title="Son izlenenler"
          items={data.map((h) => ({ ...toCard(h.content), ref: h.content.ref, key: h.id, caption: `${when(h.watched_at)} · ${minutes(h.watched_seconds)}` }))}
          onSelect={play}
        />
      ) : (
        <EmptyState icon={History} title="Geçmiş boş">İzlediğiniz içerikler burada listelenir.</EmptyState>
      )}
    </Page>
  );
}
