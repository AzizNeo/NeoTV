import { useEffect } from 'react';
import { Link, useParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Film, Play } from 'lucide-react';
import { Slot, useFeature } from '@/core/featureKit';
import { useProgressMap } from '@/features/library';
import { usePlayer } from '@/features/player';
import { EmptyState } from '@/shared/components/EmptyState/EmptyState';
import { fetchTitle, titleKeys } from '../api';
import { EpisodeList } from '../components/EpisodeList';
import { RatingBadge } from '../components/RatingBadge';
import { SimilarTitles } from '../components/SimilarTitles';
import { factLine } from '../format';
import { nextUp, remaining } from '../nextUp';
import styles from './TitleDetailPage.module.css';

export default function TitleDetailPage() {
  const { slug } = useParams();
  const { play } = usePlayer();
  const library = useFeature('library');
  const { data: detail, isLoading, isError, error } = useQuery({ queryKey: titleKeys.detail(slug), queryFn: ({ signal }) => fetchTitle(slug, { signal }) });

  const refs = detail ? [detail.play_ref, ...detail.seasons.flatMap((s) => s.episodes.map((e) => e.play_ref))] : [];
  const progress = useProgressMap(refs, { enabled: library && Boolean(detail) });

  useEffect(() => {
    if (!detail) return undefined;
    const previous = document.title;
    document.title = `${detail.card.name} — NeoTV`;
    return () => {
      document.title = previous;
    };
  }, [detail]);

  if (isLoading) return <div className={`${styles.hero} ${styles.loading}`} aria-busy="true"><div className="skeleton" /></div>;
  if (isError) {
    return (
      <EmptyState icon={Film} title={error?.code === 'TITLE_NOT_FOUND' ? 'Bu içerik bulunamadı' : 'İçerik yüklenemedi'} action={<Link to="/">Ana sayfaya dön</Link>}>
        {error?.code === 'TITLE_NOT_FOUND' ? 'Kaldırılmış olabilir ya da bu profilde görüntülenemiyor.' : error?.userMessage}
      </EmptyState>
    );
  }

  const { card } = detail;
  const next = nextUp(detail, progress);
  const left = next?.resume ? remaining(progress.get(next.ref)) : null;
  // A series plays as a queue of its available episodes: "next episode" and the in-player list come free.
  const queue = detail.seasons.flatMap((s) =>
    s.episodes
      .filter((e) => e.available && e.play_ref)
      .map((e) => ({
        ref: e.play_ref,
        title: card.name,
        subtitle: `S${s.number} B${e.number} · ${e.name}`,
        label: `${s.number}.${e.number}`,
        image: e.still_url ?? card.backdrop_url ?? undefined, // next-episode card, OS media controls
      })),
  );
  const start = (ref) => {
    const item = queue.find((q) => q.ref === ref) ?? { ref, title: card.name, image: card.backdrop_url ?? card.poster_url ?? undefined };
    play(item, card.kind === 'series' ? { queue } : undefined);
  };

  return (
    <article className={styles.page}>
      <section className={styles.hero}>
        {card.backdrop_url && <img className={styles.backdrop} src={card.backdrop_url} alt="" referrerPolicy="no-referrer" />}
        <div className={styles.scrim} />
        <div className={styles.content}>
          {detail.genre_links.length > 0 && (
            <p className={styles.genres}>
              {detail.genre_links.map((g, i) => (
                <span key={g.slug}>
                  {i > 0 && ', '}
                  <Link to={`/browse?genre=${encodeURIComponent(g.slug)}`}>{g.name}</Link>
                </span>
              ))}
            </p>
          )}
          <h1 className={styles.name}>{card.name}</h1>
          <p className={styles.facts}>
            {factLine(card).map((fact) => (
              <span key={fact}>{fact}</span>
            ))}
            <RatingBadge rating={card.rating} />
          </p>
          <div className={styles.actions}>
            {next ? (
              <button type="button" className={styles.play} onClick={() => start(next.ref)}>
                <Play size={20} fill="currentColor" aria-hidden="true" /> {next.label}
              </button>
            ) : (
              <span className={styles.unavailable}>Şu an izlenemiyor</span>
            )}
            {left && <span className={styles.left}>{left}</span>}
            {card.kind === 'movie' && detail.play_ref && (
              <span className={styles.slotActions}>
                <Slot name="content.actions" item={{ ref: detail.play_ref, title: card.name }} />
              </span>
            )}
          </div>
          {detail.synopsis && <p className={styles.synopsis}>{detail.synopsis}</p>}
        </div>
      </section>

      {card.kind === 'series' && (
        <EpisodeList seasons={detail.seasons} progress={progress} initialSeason={next?.season} onPlay={(e) => start(e.play_ref)} />
      )}
      {detail.genre_links[0] && <SimilarTitles genre={detail.genre_links[0]} exclude={card.slug} />}
    </article>
  );
}
