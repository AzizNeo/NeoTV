import { useDeferredValue, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Clapperboard, Search } from 'lucide-react';
import { Slot } from '@/core/featureKit';
import { usePlayer } from '@/features/player';
import { Button } from '@/shared/components/Button/Button';
import { ContentRow } from '@/shared/components/ContentRow/ContentRow';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { catalogKeys, fetchChannels, fetchGroups, toCard } from '../api';
import { LazyGroupRow } from '../components/LazyGroupRow';
import styles from './HomePage.module.css';

const TABS = [
  { id: 'all', label: 'Tümü', kind: undefined },
  { id: 'vod', label: 'Filmler & Diziler', kind: 'vod' },
  { id: 'live', label: 'Canlı Kanallar', kind: 'live' },
];

export default function HomePage() {
  const { play } = usePlayer();
  const [tab, setTab] = useState(TABS[0]);
  const [term, setTerm] = useState('');
  const search = useDeferredValue(term.trim());

  const groups = useQuery({ queryKey: catalogKeys.groups, queryFn: fetchGroups });
  const results = useQuery({
    queryKey: catalogKeys.search(search, tab.kind),
    queryFn: ({ signal }) => fetchChannels({ search, kind: tab.kind, perPage: 60, signal }),
    enabled: search.length >= 2,
  });

  const actions = (item) => <Slot name="content.actions" item={item} />;

  return (
    <div className={styles.page}>
      <section className={styles.hero}>
        <nav className={styles.tabs} aria-label="İçerik türü">
          {TABS.map((t) => (
            <button key={t.id} className={t.id === tab.id ? styles.activeTab : styles.tab} aria-pressed={t.id === tab.id} onClick={() => setTab(t)}>
              {t.label}
            </button>
          ))}
        </nav>
        <div className={styles.heroBody}>
          <span className={styles.kicker}>Sınırsız sinema deneyimi</span>
          <h1>
            Sonsuz hikâye. <br />
            <span>Tek ekran.</span>
          </h1>
          <form className={styles.search} role="search" onSubmit={(e) => e.preventDefault()}>
            <input type="search" placeholder="Film, dizi veya kanal ara…" value={term} onChange={(e) => setTerm(e.target.value)} aria-label="Ara" />
            <Search size={20} aria-hidden="true" className={styles.searchIcon} />
          </form>
        </div>
      </section>

      <div className={styles.rows}>
        {search.length >= 2 ? (
          results.isLoading ? (
            <Spinner />
          ) : results.data?.items.length ? (
            <ContentRow title={`"${search}" için sonuçlar`} subtitle={`${results.data.total} sonuç`} items={results.data.items.map(toCard)} onSelect={play} actions={actions} />
          ) : (
            <EmptyState icon={Search} title="Sonuç bulunamadı">Farklı bir arama deneyin.</EmptyState>
          )
        ) : (
          <>
            {/* Personal rows contributed by other features (continue watching, recommendations …). */}
            <Slot name="home.rows" onSelect={play} kind={tab.kind} />
            {groups.isLoading && <Spinner />}
            {groups.isError && (
              <EmptyState tone="error" title="Katalog yüklenemedi" action={<Button onClick={() => groups.refetch()}>Tekrar dene</Button>}>
                {groups.error.userMessage}
              </EmptyState>
            )}
            {groups.data?.length === 0 && (
              <EmptyState icon={Clapperboard} title="Kütüphane boş">
                Henüz içerik eklenmemiş. Yönetici bir oynatma listesi eklediğinde içerikler burada görünür.
              </EmptyState>
            )}
            {groups.data?.map((g) => (
              <LazyGroupRow key={`${tab.id}:${g.name}`} group={g} kind={tab.kind} onSelect={play} />
            ))}
          </>
        )}
      </div>
    </div>
  );
}
