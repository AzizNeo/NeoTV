import { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { ListVideo, Play, SkipBack, SkipForward, X } from 'lucide-react';
import { useT } from '../i18n';
import styles from './Queue.module.css';

const COUNTDOWN_S = 10;

/** Previous / next / list buttons for the control bar. */
export function QueueButtons({ live, canPrev, canNext, onPrev, onNext, onList }) {
  const t = useT();
  return (
    <>
      <button type="button" className="control-btn" onClick={onPrev} disabled={!canPrev} aria-label={t(live ? 'queue.prevChannel' : 'queue.prevEpisode')}>
        <SkipBack size={22} aria-hidden="true" />
      </button>
      <button type="button" className="control-btn" onClick={onNext} disabled={!canNext} aria-label={t(live ? 'queue.nextChannel' : 'queue.nextEpisode')}>
        <SkipForward size={22} aria-hidden="true" />
      </button>
      <button type="button" className="control-btn" onClick={onList} aria-label={t(live ? 'queue.channelList' : 'queue.episodes')}>
        <ListVideo size={22} aria-hidden="true" />
      </button>
    </>
  );
}

/**
 * The closing seconds of an episode (credits): a quiet card bottom-left. The episode keeps playing;
 * nothing happens unless the viewer asks for it. Never steals focus.
 */
export function NextEpisodeCard({ item, onPlay, onDismiss }) {
  const t = useT();
  return (
    <section className={styles.nextCard} aria-label={t('queue.nextEpisode')} aria-live="polite">
      {item.image && <img className={styles.nextThumb} src={item.image} alt="" referrerPolicy="no-referrer" />}
      <div className={styles.nextText}>
        <span className={styles.upNextLabel}>{t('queue.nextEpisode')}</span>
        <strong>{item.subtitle ?? item.title}</strong>
      </div>
      <button type="button" className={styles.primary} onClick={onPlay}>
        <Play size={16} aria-hidden="true" /> {t('play')}
      </button>
      <button type="button" className={styles.dismiss} onClick={onDismiss} aria-label={t('queue.keepWatching')}>
        <X size={16} aria-hidden="true" />
      </button>
    </section>
  );
}

/**
 * After the episode ends: a big play button in the centre whose ring empties over the countdown;
 * the next episode starts when it reaches zero, unless cancelled.
 */
export function UpNext({ item, onPlay, onCancel }) {
  const t = useT();
  const [left, setLeft] = useState(COUNTDOWN_S);
  useEffect(() => {
    const id = setInterval(() => setLeft((s) => s - 1), 1000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    if (left <= 0) onPlay();
  }, [left, onPlay]);
  return (
    <div className={styles.postPlay} role="alertdialog" aria-labelledby="upnext-title" aria-describedby="upnext-count">
      <button type="button" className={styles.ringButton} onClick={onPlay} autoFocus aria-label={t('queue.playNow', { title: item.subtitle ?? item.title })}>
        <svg className={styles.ring} viewBox="0 0 100 100" aria-hidden="true">
          <circle className={styles.ringTrack} cx="50" cy="50" r="46" />
          <circle className={styles.ringFill} cx="50" cy="50" r="46" pathLength="100" style={{ animationDuration: `${COUNTDOWN_S}s` }} />
        </svg>
        <Play size={40} aria-hidden="true" />
      </button>
      <span id="upnext-count" className={styles.upNextLabel}>
        {t('queue.countdown', { s: Math.max(left, 0) })}
      </span>
      <strong id="upnext-title" className={styles.upNextTitle}>
        {item.subtitle ?? item.title}
      </strong>
      {item.subtitle && <span className={styles.upNextSub}>{item.title}</span>}
      <button type="button" className={styles.secondary} onClick={onCancel}>
        {t('queue.cancel')}
      </button>
    </div>
  );
}

/** Side panel listing the queue (episodes or channels); the current item is marked. */
export function QueuePanel({ live, items, index, onPick, onClose }) {
  const t = useT();
  const heading = t(live ? 'queue.channels' : 'queue.episodes');
  return (
    <aside className={styles.panel} aria-label={heading}>
      <header className={styles.panelHead}>
        <h2>{heading}</h2>
        <button type="button" onClick={onClose} aria-label={t('queue.closeList')}><X size={20} aria-hidden="true" /></button>
      </header>
      <ol className={styles.panelList}>
        {items.map((item, i) => (
          <li key={item.ref}>
            <button type="button" aria-current={i === index ? 'true' : undefined} onClick={() => onPick(i)}>
              <span className={styles.panelNo}>{live ? i + 1 : item.label ?? i + 1}</span>
              <span className={styles.panelText}>
                {/* Episodes share the show's name: lead with the episode; channels lead with their name. */}
                <span>{live ? item.title : item.subtitle ?? item.title}</span>
                {live && item.caption && <small>{item.caption}</small>}
              </span>
            </button>
          </li>
        ))}
      </ol>
    </aside>
  );
}

/** Channel number + name flashed after zapping (IPTV OSD). */
export function ZapBadge({ number, title, caption }) {
  return (
    <div className={styles.zap} aria-live="polite">
      <span className={styles.zapNo}>{number}</span>
      <span>
        <strong>{title}</strong>
        {caption && <small>{caption}</small>}
      </span>
    </div>
  );
}

/** The number being typed on live TV ("12_"), or "kanal yok" when it does not exist. */
export function ChannelEntry({ digits, invalid }) {
  const t = useT();
  if (!digits) return null;
  return (
    <div className={`${styles.entry} ${invalid ? styles.entryInvalid : ''}`} role="status">
      <span className={styles.zapNo}>{digits}</span>
      {invalid ? <small>{t('queue.noChannel')}</small> : <span className={styles.caret} aria-hidden="true" />}
    </div>
  );
}

const itemShape = PropTypes.shape({
  ref: PropTypes.string.isRequired,
  title: PropTypes.string.isRequired,
  subtitle: PropTypes.string,
  caption: PropTypes.string,
  label: PropTypes.string,
  image: PropTypes.string,
});
QueueButtons.propTypes = { live: PropTypes.bool, canPrev: PropTypes.bool, canNext: PropTypes.bool, onPrev: PropTypes.func, onNext: PropTypes.func, onList: PropTypes.func };
UpNext.propTypes = { item: itemShape.isRequired, onPlay: PropTypes.func.isRequired, onCancel: PropTypes.func.isRequired };
QueuePanel.propTypes = { live: PropTypes.bool, items: PropTypes.arrayOf(itemShape).isRequired, index: PropTypes.number.isRequired, onPick: PropTypes.func.isRequired, onClose: PropTypes.func.isRequired };
ZapBadge.propTypes = { number: PropTypes.number.isRequired, title: PropTypes.string.isRequired, caption: PropTypes.string };
NextEpisodeCard.propTypes = { item: itemShape.isRequired, onPlay: PropTypes.func.isRequired, onDismiss: PropTypes.func.isRequired };
ChannelEntry.propTypes = { digits: PropTypes.string.isRequired, invalid: PropTypes.bool };
