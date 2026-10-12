import { useDeferredValue, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Clapperboard, Search } from 'lucide-react';
import { Slot, useFeature } from '@/core/featureKit';
import { usePlayer } from '@/features/player';
import { Button } from '@/shared/components/Button/Button';
import { ContentRow } from '@/shared/components/ContentRow/ContentRow';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';
import { RailSkeleton } from '@/shared/components/Rail/Rail';
import { catalogKeys, fetchChannels, fetchGroups, toCard } from '../api';
import { LazyGroupRow } from '../components/LazyGroupRow';
import styles from './HomePage.module.css';

/**
 * Home = billboard + rows contributed by other features (`home.hero`, `home.rows`) + catalogue groups.
 * With the storefront (`titles`) active, movies & series come from it, so only live groups are listed
 * here — the same film never appears twice.
 */
export default function HomePage() {
  const { play } = usePlayer();
  const storefront = useFeature('titles');
  const kind = storefront ? 'live' : undefined;
  const [term, setTerm] = useState('');
  const search = useDeferredValue(term.trim());

  const groups = useQuery({ queryKey: catalogKeys.groups, queryFn: fetchGroups });
  const results = useQuery({
    queryKey: catalogKeys.search(search, undefined),
    queryFn: ({ signal }) => fetchChannels({ search, perPage: 60, signal }),
    enabled: search.length >= 2,
  });
  const actions = (item) => <Slot name="content.actions" item={item} />;

  return (
    <div className={styles.page}>
      <Slot name="home.hero" onSelect={play} />

      <form className={styles.search} role="search" onSubmit={(e) => e.preventDefault()}>
        <Search size={18} aria-hidden="true" className={styles.searchIcon} />
        <input type="search" placeholder="Kanal veya içerik ara" value={term} onChange={(e) => setTerm(e.target.value)} aria-label="Ara" />
      </form>

      {search.length >= 2 ? (
        results.isLoading ? (
          <RailSkeleton />
        ) : results.data?.items.length ? (
          <ContentRow layout="grid" title={`"${search}" için sonuçlar`} subtitle={`${results.data.total} sonuç`} items={results.data.items.map(toCard)} onSelect={play} actions={actions} />
        ) : (
          <EmptyState icon={Search} title="Sonuç bulunamadı">Başka bir kelimeyle aramayı deneyin.</EmptyState>
        )
      ) : (
        <>
          {/* Personal and storefront rows contributed by other features (continue watching, genres, for you …). */}
          <Slot name="home.rows" onSelect={play} kind={kind} />
          {groups.isLoading && <RailSkeleton />}
          {groups.isError && (
            <EmptyState tone="error" title="Katalog yüklenemedi" action={<Button onClick={() => groups.refetch()}>Tekrar dene</Button>}>
              {groups.error.userMessage}
            </EmptyState>
          )}
          {groups.data?.length === 0 && !storefront && (
            <EmptyState icon={Clapperboard} title="Kütüphane boş">
              Yönetici bir oynatma listesi eklediğinde içerikler burada görünür.
            </EmptyState>
          )}
          {groups.data?.map((g) => (
            <LazyGroupRow key={`${kind ?? 'all'}:${g.name}`} group={g} kind={kind} onSelect={play} />
          ))}
        </>
      )}
    </div>
  );
}
