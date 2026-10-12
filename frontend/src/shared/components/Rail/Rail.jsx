import { useCallback, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import styles from './Rail.module.css';

const reducedMotion = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/**
 * Horizontal, snap-scrolling shelf. Touch/trackpad scroll natively; arrow buttons page by one
 * viewport for mouse users. Keyboard users Tab through the items and the browser scrolls the
 * focused one into view, so the arrows are pointer-only (hidden from the tab order and from AT).
 */
export function Rail({ children, size = 'landscape', label }) {
  const track = useRef(null);
  const [edges, setEdges] = useState({ start: true, end: true });

  const measure = useCallback(() => {
    const el = track.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    setEdges({ start: el.scrollLeft <= 2, end: el.scrollLeft >= max - 2 });
  }, []);

  useEffect(() => {
    const el = track.current;
    if (!el) return undefined;
    measure();
    const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(measure) : null;
    ro?.observe(el);
    return () => ro?.disconnect();
  }, [measure, children]);

  const page = (dir) => {
    const el = track.current;
    el?.scrollBy({ left: dir * el.clientWidth * 0.9, behavior: reducedMotion() ? 'auto' : 'smooth' });
  };

  return (
    <div className={styles.rail}>
      <div ref={track} className={`${styles.track} ${styles[size]}`} onScroll={measure} role="list" aria-label={label}>
        {[children].flat().filter(Boolean).map((child, i) => (
          <div key={child.key ?? i} role="listitem" className={styles.cell}>
            {child}
          </div>
        ))}
      </div>
      {!edges.start && (
        <button type="button" className={`${styles.arrow} ${styles.prev}`} onClick={() => page(-1)} tabIndex={-1} aria-hidden="true">
          <ChevronLeft size={28} />
        </button>
      )}
      {!edges.end && (
        <button type="button" className={`${styles.arrow} ${styles.next}`} onClick={() => page(1)} tabIndex={-1} aria-hidden="true">
          <ChevronRight size={28} />
        </button>
      )}
    </div>
  );
}

/** Placeholder shelf with the same geometry: no layout jump when the data arrives. */
export function RailSkeleton({ count = 6, size = 'landscape', title = true }) {
  return (
    <div className={styles.skeletonRow} aria-hidden="true">
      {title && <div className={`skeleton ${styles.skeletonTitle}`} />}
      <div className={`${styles.track} ${styles[size]}`}>
        {Array.from({ length: count }, (_, i) => (
          <div key={i} className={styles.cell}>
            <div className={`skeleton ${styles.skeletonArt}`} />
          </div>
        ))}
      </div>
    </div>
  );
}

Rail.propTypes = { children: PropTypes.node, size: PropTypes.oneOf(['landscape', 'poster']), label: PropTypes.string };
RailSkeleton.propTypes = { count: PropTypes.number, size: PropTypes.oneOf(['landscape', 'poster']), title: PropTypes.bool };
