import PropTypes from 'prop-types';
import { Baby, Lock, Rocket, User } from 'lucide-react';
import styles from './Avatar.module.css';
import { useT } from '../i18n';

const ICONS = { 'kids-bear': Baby, 'kids-rocket': Rocket };

export function Avatar({ avatar = 'default', size = 120, locked = false }) {
  const t = useT();
  const Icon = ICONS[avatar] ?? User;
  return (
    <span className={`${styles.avatar} ${styles[avatar] ?? ''}`} style={{ width: size, height: size }}>
      <Icon size={size * 0.5} aria-hidden="true" />
      {locked && (
        <span className={styles.lock}>
          <Lock size={14} aria-label={t('locked')} />
        </span>
      )}
    </span>
  );
}

Avatar.propTypes = { avatar: PropTypes.string, size: PropTypes.number, locked: PropTypes.bool };
