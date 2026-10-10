import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Radio } from 'lucide-react';
import { api } from '@/core/api/client';
import { Slot } from '@/core/featureKit';
import { usePlayer } from '@/features/player';
import { ContentRow } from '@/shared/components/ContentRow/ContentRow';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';
import { Page } from '@/shared/components/Page/Page';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { GuideGrid } from './GuideGrid';

const time = (iso) => new Date(iso).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });

export default function LiveTvPage() {
  const { play } = usePlayer();
  const channels = useQuery({ queryKey: ['live', 'channels'], queryFn: () => api.call('live_list_channels'), refetchInterval: 60_000 });
  const guide = useQuery({
    queryKey: ['live', 'guide'],
    queryFn: () => api.call('live_guide', { query: { hours: 6 } }),
    enabled: Boolean(channels.data?.length),
    staleTime: 5 * 60_000,
  });

  const cards = useMemo(
    () =>
      (channels.data ?? []).map((c) => ({
        ref: c.ref,
        title: c.name,
        image: c.logo,
        live: c.is_live,
        caption: c.now ? `${time(c.now.starts_at)} ${c.now.title}${c.next ? ` · Sonra: ${c.next.title}` : ''}` : c.description ?? undefined,
      })),
    [channels.data],
  );

  if (channels.isLoading) return <Spinner fullScreen />;
  if (!cards.length) {
    return (
      <EmptyState icon={Radio} title="Canlı kanal yok">
        Yönetici canlı kanal eklediğinde burada görünecek.
      </EmptyState>
    );
  }

  return (
    <Page title="Canlı TV" subtitle="Şu an yayında olanlar ve yayın akışı">
      <ContentRow title="Kanallar" items={cards} onSelect={play} actions={(item) => <Slot name="content.actions" item={item} />} />
      {guide.data?.length > 0 && <GuideGrid channels={channels.data} programs={guide.data} onSelect={play} />}
    </Page>
  );
}
