import PropTypes from 'prop-types';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/core/api/client';
import { Rail } from '@/shared/components/Rail/Rail';
import { titleKeys } from '../api';
import { useT } from '../i18n';
import { TitleCard } from './TitleCard';
import styles from './Titles.module.css';

/** "More like this": the title's first genre, newest first, without the title itself. */
export function SimilarTitles({ genre, exclude }) {
  const t = useT();
  const query = { genre: genre.slug, sort: 'recent', per_page: 16 };
  const { data } = useQuery({ queryKey: titleKeys.browse(query), queryFn: ({ signal }) => api.call('titles_browse', { query, signal }), staleTime: 60_000 });
  const items = (data?.items ?? []).filter((c) => c.slug !== exclude);
  if (!items.length) return null;
  return (
    <section className={styles.shelf} aria-label={t('similar')}>
      <h2 className={styles.shelfTitle}>{t('similar')}</h2>
      <Rail size="poster" label={t('similar')}>
        {items.map((card) => (
          <TitleCard key={card.slug} card={card} />
        ))}
      </Rail>
    </section>
  );
}
SimilarTitles.propTypes = { genre: PropTypes.shape({ slug: PropTypes.string.isRequired, name: PropTypes.string.isRequired }).isRequired, exclude: PropTypes.string.isRequired };
