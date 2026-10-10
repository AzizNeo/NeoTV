import PropTypes from 'prop-types';
import styles from './Page.module.css';

export function Page({ title, subtitle, actions, children, width = 'wide' }) {
  return (
    <div className={`${styles.page} ${styles[width]}`}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>{title}</h1>
          {subtitle && <p className={styles.subtitle}>{subtitle}</p>}
        </div>
        {actions && <div className={styles.actions}>{actions}</div>}
      </header>
      {children}
    </div>
  );
}

export function Panel({ title, children, actions }) {
  return (
    <section className={styles.panel}>
      {(title || actions) && (
        <header className={styles.panelHeader}>
          {title && <h2>{title}</h2>}
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

Page.propTypes = {
  title: PropTypes.string.isRequired,
  subtitle: PropTypes.node,
  actions: PropTypes.node,
  children: PropTypes.node,
  width: PropTypes.oneOf(['wide', 'narrow']),
};
Panel.propTypes = { title: PropTypes.string, children: PropTypes.node, actions: PropTypes.node };
