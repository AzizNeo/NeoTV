import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import { factLine } from '../format';
import { titleCardShape } from '../shapes';
import styles from './Titles.module.css';

/** Poster card → the title's detail page. Unplayable titles stay visible but are marked. */
export function TitleCard({ card }) {
  const facts = factLine(card);
  return (
    <Link to={`/title/${card.slug}`} className={styles.card} aria-label={`${card.name}${card.available ? '' : ' (şu an izlenemiyor)'}`}>
      <span className={styles.poster}>
        {card.poster_url ? (
          <img src={card.poster_url} alt="" loading="lazy" referrerPolicy="no-referrer" />
        ) : (
          <span className={styles.posterFallback}>{card.name}</span>
        )}
        {!card.available && <span className={styles.unavailable}>Şu an izlenemiyor</span>}
      </span>
      <span className={styles.cardName}>{card.name}</span>
      {facts.length > 0 && <span className={styles.cardFacts}>{facts.join(' · ')}</span>}
    </Link>
  );
}

TitleCard.propTypes = { card: titleCardShape.isRequired };
