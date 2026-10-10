import PropTypes from 'prop-types';
import styles from './EmptyState.module.css';

export function EmptyState({ icon: Icon, title, children, action, tone = 'neutral' }) {
  return (
    <div className={`${styles.box} ${styles[tone]}`} role={tone === 'error' ? 'alert' : undefined}>
      {Icon && <Icon size={40} aria-hidden="true" className={styles.icon} />}
      <h2 className={styles.title}>{title}</h2>
      {children && <div className={styles.body}>{children}</div>}
      {action && <div className={styles.action}>{action}</div>}
    </div>
  );
}

EmptyState.propTypes = {
  icon: PropTypes.elementType,
  title: PropTypes.string.isRequired,
  children: PropTypes.node,
  action: PropTypes.node,
  tone: PropTypes.oneOf(['neutral', 'error']),
};
