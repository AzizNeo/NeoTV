import { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { ListVideo, SkipBack, SkipForward, X } from 'lucide-react';
import styles from './Queue.module.css';

const COUNTDOWN_S = 10;

/** Previous / next / list buttons for the control bar. */
export function QueueButtons({ live, canPrev, canNext, onPrev, onNext, onList }) {
  return (
    <>
      <button type="button" className="control-btn" onClick={onPrev} disabled={!canPrev} aria-label={live ? 'Önceki kanal' : 'Önceki bölüm'}>
        <SkipBack size={22} aria-hidden="true" />
      </button>
      <button type="button" className="control-btn" onClick={onNext} disabled={!canNext} aria-label={live ? 'Sonraki kanal' : 'Sonraki bölüm'}>
        <SkipForward size={22} aria-hidden="true" />
      </button>
      <button type="button" className="control-btn" onClick={onList} aria-label={live ? 'Kanal listesi' : 'Bölümler'}>
        <ListVideo size={22} aria-hidden="true" />
      </button>
    </>
  );
}

/** "Up next" card after an episode ends: plays the next one after a countdown unless cancelled. */
export function UpNext({ item, onPlay, onCancel }) {
  const [left, setLeft] = useState(COUNTDOWN_S);
  useEffect(() => {
    const id = setInterval(() => setLeft((s) => s - 1), 1000);
    return () => clearInterval(id);
  }, []);
  useEffect(() => {
    if (left <= 0) onPlay();
  }, [left, onPlay]);
  return (
    <div className={styles.upNext} role="alertdialog" aria-label="Sıradaki bölüm">
      <span className={styles.upNextLabel}>Sıradaki · {Math.max(left, 0)} sn</span>
      <strong className={styles.upNextTitle}>{item.title}</strong>
      {item.subtitle && <span className={styles.upNextSub}>{item.subtitle}</span>}
      <div className={styles.upNextActions}>
        <button type="button" className={styles.primary} onClick={onPlay} autoFocus>Şimdi oynat</button>
        <button type="button" className={styles.secondary} onClick={onCancel}>İptal</button>
      </div>
    </div>
  );
}

/** Side panel listing the queue (episodes or channels); the current item is marked. */
export function QueuePanel({ live, items, index, onPick, onClose }) {
  return (
    <aside className={styles.panel} aria-label={live ? 'Kanallar' : 'Bölümler'}>
      <header className={styles.panelHead}>
        <h2>{live ? 'Kanallar' : 'Bölümler'}</h2>
        <button type="button" onClick={onClose} aria-label="Listeyi kapat"><X size={20} aria-hidden="true" /></button>
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

const itemShape = PropTypes.shape({ ref: PropTypes.string.isRequired, title: PropTypes.string.isRequired, subtitle: PropTypes.string, caption: PropTypes.string, label: PropTypes.string });
QueueButtons.propTypes = { live: PropTypes.bool, canPrev: PropTypes.bool, canNext: PropTypes.bool, onPrev: PropTypes.func, onNext: PropTypes.func, onList: PropTypes.func };
UpNext.propTypes = { item: itemShape.isRequired, onPlay: PropTypes.func.isRequired, onCancel: PropTypes.func.isRequired };
QueuePanel.propTypes = { live: PropTypes.bool, items: PropTypes.arrayOf(itemShape).isRequired, index: PropTypes.number.isRequired, onPick: PropTypes.func.isRequired, onClose: PropTypes.func.isRequired };
ZapBadge.propTypes = { number: PropTypes.number.isRequired, title: PropTypes.string.isRequired, caption: PropTypes.string };
