import PropTypes from 'prop-types';

/** Shape of a title card as returned by the titles API (TitleCardOut). */
export const titleCardShape = PropTypes.shape({
  slug: PropTypes.string.isRequired,
  kind: PropTypes.oneOf(['movie', 'series']).isRequired,
  name: PropTypes.string.isRequired,
  year: PropTypes.number,
  rating: PropTypes.string.isRequired,
  runtime_minutes: PropTypes.number,
  season_count: PropTypes.number,
  genres: PropTypes.arrayOf(PropTypes.string).isRequired,
  poster_url: PropTypes.string,
  backdrop_url: PropTypes.string,
  available: PropTypes.bool.isRequired,
});
