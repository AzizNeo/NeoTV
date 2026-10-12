import PropTypes from 'prop-types';
import { ratingLabel, ratingShort } from '../format';
import styles from './Titles.module.css';

export function RatingBadge({ rating }) {
  return (
    <abbr className={styles.rating} title={ratingLabel(rating)}>
      {ratingShort(rating)}
    </abbr>
  );
}
RatingBadge.propTypes = { rating: PropTypes.string.isRequired };
