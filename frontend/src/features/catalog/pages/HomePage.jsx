import { useQuery } from '@tanstack/react-query';
import { Clapperboard } from 'lucide-react';
import { Slot, useFeature } from '@/core/featureKit';
import { usePlayer } from '@/features/player';
import { Button } from '@/shared/components/Button/Button';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';
import { RailSkeleton } from '@/shared/components/Rail/Rail';
import { catalogKeys, fetchGroups } from '../api';
import { LazyGroupRow } from '../components/LazyGroupRow';
import styles from './HomePage.module.css';
import { useT } from '../i18n';

/**
 * Home = billboard + rows contributed by other features (`home.hero`, `home.rows`) + catalogue groups.
 * With the storefront (`titles`) active, movies & series come from it, so only live groups are listed
 * here — the same film never appears twice.
 */
export default function HomePage() {
  const t = useT();
  const { play } = usePlayer();
  const storefront = useFeature('titles');
  const kind = storefront ? 'live' : undefined;

  const groups = useQuery({ queryKey: catalogKeys.groups, queryFn: fetchGroups });

  return (
    <div className={styles.page}>
      <Slot name="home.hero" onSelect={play} />
      {/* Personal and storefront rows contributed by other features (continue watching, genres, for you …). */}
      <Slot name="home.rows" onSelect={play} kind={kind} />
      {groups.isLoading && <RailSkeleton />}
      {groups.isError && (
        <EmptyState tone="error" title={t('loadFailed')} action={<Button onClick={() => groups.refetch()}>{t('retry')}</Button>}>
          {groups.error.userMessage}
        </EmptyState>
      )}
      {groups.data?.length === 0 && !storefront && (
        <EmptyState icon={Clapperboard} title={t('empty')}>
          {t('emptyBody')}
        </EmptyState>
      )}
      {groups.data?.map((g) => (
        <LazyGroupRow key={`${kind ?? 'all'}:${g.name}`} group={g} kind={kind} onSelect={play} />
      ))}
    </div>
  );
}
