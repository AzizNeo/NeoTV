import { useState } from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { Info, Play } from 'lucide-react';
import { fetchFeatured, titleKeys } from '../api';
import { factLine } from '../format';
import { useT } from '../i18n';
import { RatingBadge } from './RatingBadge';
import styles from './Hero.module.css';

/**
 * Contributed to `home.hero`: the featured titles (playable only — the API filters).
 * No auto-rotation: switching is the viewer's choice (motion only answers an action).
 */
export function HeroBillboard({ onSelect }) {
  const t = useT();
  const { data, isLoading } = useQuery({ queryKey: titleKeys.featured, queryFn: fetchFeatured, staleTime: 60_000 });
  const [index, setIndex] = useState(0);

  if (isLoading) return <div className={`${styles.hero} ${styles.loading}`} aria-hidden="true"><div className="skeleton" /></div>;
  if (!data?.length) return null;

  const current = data[Math.min(index, data.length - 1)];
  const { card } = current;
  return (
    <section className={styles.hero} aria-roledescription={t('heroRole')} aria-label={card.name}>
      {card.backdrop_url && <img key={card.slug} className={styles.backdrop} src={card.backdrop_url} alt="" referrerPolicy="no-referrer" />}
      <div className={styles.scrim} />
      <div className={styles.content}>
        {card.genres.length > 0 && <p className={styles.genres}>{card.genres.join(', ')}</p>}
        <h1 className={styles.name}>{card.name}</h1>
        <p className={styles.facts}>
          {factLine(card, t).map((fact) => (
            <span key={fact}>{fact}</span>
          ))}
          <RatingBadge rating={card.rating} />
        </p>
        {current.synopsis && <p className={styles.synopsis}>{current.synopsis}</p>}
        <div className={styles.actions}>
          <button type="button" className={styles.play} onClick={() => onSelect?.({ ref: current.play_ref, title: card.name })}>
            <Play size={20} fill="currentColor" aria-hidden="true" /> {t('play')}
          </button>
          <Link to={`/title/${card.slug}`} className={styles.more}>
            <Info size={20} aria-hidden="true" /> {t('details')}
          </Link>
        </div>
      </div>
      {data.length > 1 && (
        <div className={styles.picker} role="group" aria-label={t('heroPick')}>
          {data.map(({ card: c }, i) => (
            <button
              key={c.slug}
              type="button"
              className={i === index ? styles.pickActive : styles.pick}
              aria-pressed={i === index}
              aria-label={c.name}
              onClick={() => setIndex(i)}
            >
              {c.backdrop_url && <img src={c.backdrop_url} alt="" referrerPolicy="no-referrer" />}
              <span aria-hidden="true">{c.name}</span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
HeroBillboard.propTypes = { onSelect: PropTypes.func };
