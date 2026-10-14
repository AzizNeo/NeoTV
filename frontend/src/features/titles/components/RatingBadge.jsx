import PropTypes from 'prop-types';
import { ratingLabel, ratingShort } from '../format';
import { useT } from '../i18n';
import styles from './Titles.module.css';

export function RatingBadge({ rating }) {
  const t = useT();
  return (
    <abbr className={styles.rating} title={ratingLabel(rating, t)}>
      {ratingShort(rating)}
    </abbr>
  );
}
RatingBadge.propTypes = { rating: PropTypes.string.isRequired };
