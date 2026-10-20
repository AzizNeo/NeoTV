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
import { fetchLiveChannels, liveKeys, toLiveCard } from '../api';
import { GuideGrid } from './GuideGrid';
import { useT } from '../i18n';

const GUIDE_BACK_HOURS = 3;
/** The guide's first hour (on the half hour), `back` hours ago — as the grid draws it. */
const guideStart = (back) => {
  const start = new Date(Date.now() - back * 3_600_000);
  start.setMinutes(start.getMinutes() < 30 ? 0 : 30, 0, 0);
  return start.toISOString();
};

export default function LiveTvPage() {
  const t = useT();
  const { play } = usePlayer();
  const channels = useQuery({ queryKey: liveKeys.channels, queryFn: fetchLiveChannels, refetchInterval: 60_000 });
  // Catch-up (ADR-0012): with any archived channel, the guide also shows the last hours.
  const back = channels.data?.some((c) => c.catchup_days > 0) ? GUIDE_BACK_HOURS : 0;
  const guide = useQuery({
    queryKey: [...liveKeys.guide, back],
    queryFn: () => api.call('live_guide', { query: { hours: 6 + back, start: guideStart(back) } }),
    enabled: Boolean(channels.data?.length),
    staleTime: 5 * 60_000,
  });

  const cards = useMemo(() => (channels.data ?? []).map((c) => toLiveCard(c, t)), [channels.data, t]);
  // Channel list = play queue: ↑/↓ and the in-player list zap through it, numbered in this order.
  const zap = (item) => play(item, { queue: cards });

  if (channels.isLoading) return <Spinner fullScreen />;
  if (!cards.length) {
    return (
      <EmptyState icon={Radio} title={t('empty')}>
        {t('emptyBody')}
      </EmptyState>
    );
  }

  return (
    <Page title={t('title')} subtitle={t('subtitle')}>
      <ContentRow title={t('channelsRow')} items={cards} onSelect={zap} actions={(item) => <Slot name="content.actions" item={item} />} />
      {guide.data?.length > 0 && (
        <GuideGrid channels={channels.data} programs={guide.data} onSelect={zap} onCatchup={(item) => play(item)} back={back} />
      )}
    </Page>
  );
}
