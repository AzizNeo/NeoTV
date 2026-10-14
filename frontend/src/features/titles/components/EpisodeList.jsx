import { useId, useState } from 'react';
import PropTypes from 'prop-types';
import { Play } from 'lucide-react';
import { duration } from '../format';
import { useT } from '../i18n';
import styles from '../pages/TitleDetailPage.module.css';

/** Season picker + episodes with resume progress. Unavailable episodes stay listed but cannot start. */
export function EpisodeList({ seasons, progress, initialSeason, onPlay }) {
  const t = useT();
  const selectId = useId();
  const [chosen, setChosen] = useState(null); // null → follow initialSeason (next-up) until the viewer picks
  const number = chosen ?? initialSeason ?? seasons[0]?.number;
  const season = seasons.find((s) => s.number === number) ?? seasons[0];
  if (!season) return null;

  return (
    <section className={styles.episodes} aria-labelledby={`${selectId}-h`}>
      <header className={styles.episodesHeader}>
        <h2 id={`${selectId}-h`}>{t('episodes.title')}</h2>
        {seasons.length > 1 ? (
          <select id={selectId} className={styles.season} value={season.number} onChange={(e) => setChosen(Number(e.target.value))} aria-label={t('episodes.season')}>
            {seasons.map((s) => (
              <option key={s.number} value={s.number}>
                {s.name || (s.number === 0 ? t('episodes.specials') : t('episodes.seasonN', { n: s.number }))}
              </option>
            ))}
          </select>
        ) : (
          <span className={styles.seasonName}>{season.name || t('episodes.seasonN', { n: season.number })}</span>
        )}
      </header>
      <ol className={styles.episodeList}>
        {season.episodes.map((e) => {
          const p = progress.get(e.play_ref);
          const percent = p ? (p.completed ? 100 : p.progress_percent) : 0;
          return (
            <li key={e.number}>
              <button type="button" className={styles.episode} disabled={!e.available} onClick={() => onPlay(e, season.number)}>
                <span className={styles.epNumber}>{e.number}</span>
                <span className={styles.epBody}>
                  <span className={styles.epTitle}>
                    {e.name}
                    {e.runtime_minutes ? <span className={styles.epTime}>{duration(e.runtime_minutes, t)}</span> : null}
                  </span>
                  {e.synopsis && <span className={styles.epSynopsis}>{e.synopsis}</span>}
                  {!e.available && <span className={styles.epUnavailable}>{t('unavailable')}</span>}
                  {percent > 0 && (
                    <span className={styles.epProgress} role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} aria-label={t('episodes.watched')}>
                      <span style={{ width: `${percent}%` }} />
                    </span>
                  )}
                </span>
                {e.available && <Play size={18} aria-hidden="true" className={styles.epPlay} />}
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

EpisodeList.propTypes = {
  seasons: PropTypes.arrayOf(PropTypes.shape({ number: PropTypes.number.isRequired, name: PropTypes.string, episodes: PropTypes.array.isRequired })).isRequired,
  progress: PropTypes.instanceOf(Map).isRequired,
  initialSeason: PropTypes.number,
  onPlay: PropTypes.func.isRequired,
};
