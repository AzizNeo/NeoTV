import PropTypes from 'prop-types';
import { Lock, Radio } from 'lucide-react';
import { Rail } from '../Rail/Rail';
import styles from './ContentRow.module.css';
import { useSharedText } from '../SharedText/SharedTextProvider';

/**
 * Presentational row of content cards (catalog, live, library and
 * recommendations all render through this — one look, many sources).
 * `actions(item)` renders per-card extras (e.g. a favourite toggle from the
 * library feature) without this component knowing about them.
 */
export function ContentRow({ title, subtitle, items, onSelect, actions, variant = 'landscape', layout = 'rail' }) {
  if (!items?.length) return null;
  const cards = items.map((item) => (
    <ContentCard key={item.key ?? item.ref} item={item} onSelect={onSelect} actions={actions} variant={variant} />
  ));
  return (
    <section className={styles.row} aria-label={title}>
      <header className={styles.header}>
        <h2 className={styles.title}>{title}</h2>
        {subtitle && <span className={styles.subtitle}>{subtitle}</span>}
      </header>
      {layout === 'rail' ? (
        <Rail size={variant} label={title}>{cards}</Rail>
      ) : (
        <div className={`${styles.grid} ${styles[variant]}`}>{cards}</div>
      )}
    </section>
  );
}

export function ContentCard({ item, onSelect, actions, variant = 'landscape' }) {
  const text = useSharedText();
  const label = item.reason ? `${item.title} — ${item.reason}` : item.title;
  // The button's name says everything its picture shows (title, live); the picture's own texts are
  // hidden from assistive technology so the name never differs from what is visible (WCAG 2.5.3).
  const name = item.live ? `${text.playItem(item.title)}, ${text.live}` : text.playItem(item.title);
  return (
    <article className={`${styles.card} ${styles[variant]}`}>
      <button type="button" className={styles.hit} onClick={() => onSelect?.(item)} aria-label={name} title={label}>
        <div className={styles.art}>
          {item.image ? (
            <img src={item.image} alt="" loading="lazy" referrerPolicy="no-referrer" className={styles.img} />
          ) : (
            <span className={styles.placeholder} aria-hidden="true">{item.title}</span>
          )}
          {item.live && (
            <span className={styles.liveBadge} aria-hidden="true">
              <Radio size={12} /> {text.live}
            </span>
          )}
          {item.locked && (
            <span className={styles.lock}>
              <Lock size={14} aria-hidden="true" />
            </span>
          )}
          {item.progress > 0 && (
            <span className={styles.progress} aria-hidden="true">
              <span style={{ width: `${Math.min(100, item.progress)}%` }} />
            </span>
          )}
        </div>
      </button>
      <div className={styles.meta}>
        <span className={styles.name}>{item.title}</span>
        {actions && <span className={styles.actions}>{actions(item)}</span>}
      </div>
      {item.caption && <div className={styles.caption}>{item.caption}</div>}
    </article>
  );
}

const itemShape = PropTypes.shape({
  ref: PropTypes.string.isRequired,
  title: PropTypes.string.isRequired,
  image: PropTypes.string,
  progress: PropTypes.number,
  live: PropTypes.bool,
  locked: PropTypes.bool,
  caption: PropTypes.string,
  reason: PropTypes.string,
});

ContentRow.propTypes = {
  title: PropTypes.string.isRequired,
  subtitle: PropTypes.string,
  items: PropTypes.arrayOf(itemShape),
  onSelect: PropTypes.func,
  actions: PropTypes.func,
  variant: PropTypes.oneOf(['landscape', 'poster']),
  layout: PropTypes.oneOf(['rail', 'grid']),
};
ContentCard.propTypes = { item: itemShape.isRequired, onSelect: PropTypes.func, actions: PropTypes.func, variant: PropTypes.string };
