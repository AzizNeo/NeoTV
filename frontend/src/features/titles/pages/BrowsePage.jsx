import { useEffect, useRef, useState } from 'react';
import { useLocation, useSearchParams } from 'react-router-dom';
import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { Clapperboard, History, Search, X } from 'lucide-react';
import { api } from '@/core/api/client';
import { Slot } from '@/core/featureKit';
import { useProfile } from '@/features/profiles';
import { Button } from '@/shared/components/Button/Button';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';
import { titleKeys } from '../api';
import { DECADES, KINDS, SORTS, isFiltered, readFilters, toApiQuery, writeFilters } from '../browseParams';
import { TitleCard } from '../components/TitleCard';
import { useRecentSearches } from '../hooks/useRecentSearches';
import styles from './BrowsePage.module.css';

const PER_PAGE = 30;
const DEBOUNCE_MS = 300;

export default function BrowsePage() {
  const [params, setParams] = useSearchParams();
  const filters = readFilters(params);
  const location = useLocation();
  const { current } = useProfile();
  const { recent, remember, clear } = useRecentSearches(current?.id ?? 'device');
  const input = useRef(null);
  const sentinel = useRef(null);

  // The field is typed into freely; the URL follows after a pause (one history entry, not one per key).
  const [term, setTerm] = useState(filters.q);
  const [written, setWritten] = useState(filters.q);
  const [syncedQ, setSyncedQ] = useState(filters.q);
  const [focused, setFocused] = useState(false);
  if (filters.q !== syncedQ) {
    // URL changed (Back button, a recent search…): adopt it unless it is our own debounced write.
    setSyncedQ(filters.q);
    if (filters.q !== written) setTerm(filters.q);
  }

  const update = (patch, options) => setParams(writeFilters({ ...filters, ...patch }), options);

  useEffect(() => {
    const value = term.trim();
    if (value === filters.q) return undefined;
    const id = setTimeout(() => {
      setWritten(value);
      setParams(writeFilters({ ...filters, q: value }), { replace: true });
    }, DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [term, filters, setParams]);

  useEffect(() => {
    if (location.state?.focusSearch) input.current?.focus();
  }, [location.state?.focusSearch]);

  const genres = useQuery({ queryKey: titleKeys.genres, queryFn: () => api.call('titles_genres'), staleTime: 5 * 60_000 });
  const apiQuery = toApiQuery(filters, PER_PAGE);
  const results = useInfiniteQuery({
    queryKey: titleKeys.browse(apiQuery),
    queryFn: ({ pageParam, signal }) => api.call('titles_browse', { query: { ...apiQuery, page: pageParam }, signal }),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.page * last.per_page < last.total ? last.page + 1 : undefined),
  });
  const items = results.data?.pages.flatMap((p) => p.items) ?? [];
  const total = results.data?.pages[0]?.total ?? 0;
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = results;

  useEffect(() => {
    const node = sentinel.current;
    if (!node || !hasNextPage || !('IntersectionObserver' in window)) return undefined;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting) && !isFetchingNextPage) fetchNextPage();
    }, { rootMargin: '800px 0px' });
    io.observe(node);
    return () => io.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const showRecent = focused && !term && recent.length > 0;
  const searching = filters.q.length >= 2;

  return (
    <div className={styles.page}>
      <h1 className={styles.heading}>{searching ? 'Arama' : 'Filmler ve diziler'}</h1>

      <form
        className={styles.searchBox}
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          remember(term);
        }}
      >
        <Search size={20} aria-hidden="true" className={styles.searchIcon} />
        <input
          ref={input}
          type="search"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setTimeout(() => setFocused(false), 150) /* let a click on a recent item land */}
          placeholder="Film, dizi veya kanal ara"
          aria-label="Ara"
          enterKeyHint="search"
          maxLength={100}
        />
        {term && (
          <button type="button" className={styles.clearTerm} aria-label="Aramayı temizle" onClick={() => { setTerm(''); input.current?.focus(); }}>
            <X size={18} aria-hidden="true" />
          </button>
        )}
        {showRecent && (
          <div className={styles.recent}>
            <div className={styles.recentHead}>
              <span>Son aramalar</span>
              <button type="button" onClick={clear}>Temizle</button>
            </div>
            <ul>
              {recent.map((s) => (
                <li key={s}>
                  <button type="button" onClick={() => { setTerm(s); update({ q: s }); }}>
                    <History size={16} aria-hidden="true" /> {s}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </form>

      <div className={styles.filters}>
        <div className={styles.chips} role="group" aria-label="Tür">
          <button type="button" className={styles.chip} aria-pressed={!filters.genre} onClick={() => update({ genre: '' })}>Tüm türler</button>
          {(genres.data ?? []).map((g) => (
            <button key={g.slug} type="button" className={styles.chip} aria-pressed={filters.genre === g.slug} onClick={() => update({ genre: filters.genre === g.slug ? '' : g.slug })}>
              {g.name}
            </button>
          ))}
        </div>
        <div className={styles.controls}>
          <div className={styles.segmented} role="group" aria-label="İçerik türü">
            {KINDS.map((k) => (
              <button key={k.id || 'all'} type="button" aria-pressed={filters.kind === k.id} onClick={() => update({ kind: k.id })}>{k.label}</button>
            ))}
          </div>
          <select className={styles.select} value={filters.decade} onChange={(e) => update({ decade: e.target.value })} aria-label="Yıl">
            {DECADES.map((d) => <option key={d.id || 'all'} value={d.id}>{d.label}</option>)}
          </select>
          <select className={styles.select} value={filters.sort} onChange={(e) => update({ sort: e.target.value })} aria-label="Sıralama">
            {SORTS.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
        </div>
      </div>

      {searching && <Slot name="search.results" query={filters.q} />}

      <section aria-label="Sonuçlar" aria-busy={results.isFetching} onClickCapture={() => searching && remember(filters.q)}>
        {results.isLoading ? (
          <div className={styles.grid} aria-hidden="true">
            {Array.from({ length: 12 }, (_, i) => <div key={i} className={`skeleton ${styles.skeletonCard}`} />)}
          </div>
        ) : results.isError ? (
          <EmptyState tone="error" title="Liste yüklenemedi" action={<Button onClick={() => results.refetch()}>Tekrar dene</Button>}>{results.error.userMessage}</EmptyState>
        ) : items.length === 0 && searching ? (
          // Other features may have matched (live channels above): a quiet line, not a full-page "nothing found".
          <p className={styles.noTitles}>
            &quot;{filters.q}&quot; ile eşleşen film veya dizi yok.{' '}
            <button type="button" onClick={() => { setTerm(''); setParams(new URLSearchParams()); }}>Aramayı temizle</button>
          </p>
        ) : items.length === 0 ? (
          <EmptyState icon={Clapperboard} title="Bu filtrelere uyan içerik yok"
            action={isFiltered(filters) ? <Button variant="secondary" onClick={() => { setTerm(''); setParams(new URLSearchParams()); }}>Filtreleri temizle</Button> : null}>
            Filtrelerden birini kaldırmayı deneyin.
          </EmptyState>
        ) : (
          <>
            <p className={styles.count} aria-live="polite">{total} sonuç</p>
            <div className={styles.grid}>
              {items.map((card) => <TitleCard key={card.slug} card={card} />)}
            </div>
            <div ref={sentinel} className={styles.more}>
              {hasNextPage && (
                <Button variant="secondary" onClick={() => fetchNextPage()} disabled={isFetchingNextPage}>
                  {isFetchingNextPage ? 'Yükleniyor…' : 'Daha fazla göster'}
                </Button>
              )}
            </div>
          </>
        )}
      </section>
    </div>
  );
}
