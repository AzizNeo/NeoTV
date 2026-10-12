import { useQuery } from '@tanstack/react-query';
import { Rail, RailSkeleton } from '@/shared/components/Rail/Rail';
import { fetchRails, titleKeys } from '../api';
import { TitleCard } from './TitleCard';
import styles from './Titles.module.css';

/** Contributed to `home.rows`: one shelf per genre (biggest first, featured titles first). */
export function TitleRails() {
  const { data, isLoading } = useQuery({ queryKey: titleKeys.rails, queryFn: fetchRails, staleTime: 60_000 });
  if (isLoading) return <RailSkeleton size="poster" />;
  return (data ?? []).map((rail) => (
    <section key={rail.genre.slug} className={styles.shelf} aria-label={rail.genre.name}>
      <h2 className={styles.shelfTitle}>{rail.genre.name}</h2>
      <Rail size="poster" label={rail.genre.name}>
        {rail.items.map((card) => (
          <TitleCard key={card.slug} card={card} />
        ))}
      </Rail>
    </section>
  ));
}
