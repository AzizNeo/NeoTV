import { useQuery } from '@tanstack/react-query';
import { Heart } from 'lucide-react';
import { api } from '@/core/api/client';
import { Slot } from '@/core/featureKit';
import { usePlayer } from '@/features/player';
import { ContentRow } from '@/shared/components/ContentRow/ContentRow';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';
import { Page } from '@/shared/components/Page/Page';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { libraryKeys, toCard } from '../api';
import { useT } from '../i18n';

export default function FavoritesPage() {
  const t = useT();
  const { play } = usePlayer();
  const { data, isLoading } = useQuery({ queryKey: libraryKeys.favorites, queryFn: () => api.call('library_favorites', { query: { limit: 200 } }) });
  if (isLoading) return <Spinner fullScreen />;
  return (
    <Page title={t('favorites.title')}>
      {data?.length ? (
        <ContentRow layout="grid" title={t('favorites.count', { count: data.length })} items={data.map((f) => toCard(f.content))} onSelect={play} actions={(item) => <Slot name="content.actions" item={item} />} />
      ) : (
        <EmptyState icon={Heart} title={t('favorites.empty')}>
          {t('favorites.emptyBody')}
        </EmptyState>
      )}
    </Page>
  );
}
