import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import { factLine } from '../format';
import { useT } from '../i18n';
import { titleCardShape } from '../shapes';
import styles from './Titles.module.css';

/**
 * Poster card → the title's detail page. Unplayable titles stay visible but are marked.
 *
 * No aria-label: the link's accessible name is its visible text — name, facts, status — so what a
 * voice-control user reads on screen is what they can say (WCAG 2.5.3). The poster's copies of the
 * name and of the status are hidden from assistive technology so each is announced once, name first.
 */
export function TitleCard({ card }) {
  const t = useT();
  const facts = factLine(card, t);
  return (
    <Link to={`/title/${card.slug}`} className={styles.card}>
      <span className={styles.poster}>
        {card.poster_url ? (
          <img src={card.poster_url} alt="" loading="lazy" referrerPolicy="no-referrer" />
        ) : (
          <span className={styles.posterFallback} aria-hidden="true">{card.name}</span>
        )}
        {!card.available && <span className={styles.unavailable} aria-hidden="true">{t('unavailable')}</span>}
      </span>
      <span className={styles.cardName}>{card.name}</span>
      {facts.length > 0 && <span className={styles.cardFacts}>{facts.join(' · ')}</span>}
      {!card.available && <span className="visually-hidden">, {t('unavailable')}</span>}
    </Link>
  );
}

TitleCard.propTypes = { card: titleCardShape.isRequired };
