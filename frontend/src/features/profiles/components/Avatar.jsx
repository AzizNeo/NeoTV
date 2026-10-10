import PropTypes from 'prop-types';
import { Baby, Lock, Rocket, User } from 'lucide-react';
import styles from './Avatar.module.css';

const ICONS = { 'kids-bear': Baby, 'kids-rocket': Rocket };

export function Avatar({ avatar = 'default', size = 120, locked = false }) {
  const Icon = ICONS[avatar] ?? User;
  return (
    <span className={`${styles.avatar} ${styles[avatar] ?? ''}`} style={{ width: size, height: size }}>
      <Icon size={size * 0.5} aria-hidden="true" />
      {locked && (
        <span className={styles.lock}>
          <Lock size={14} aria-label="PIN korumalı" />
        </span>
      )}
    </span>
  );
}

Avatar.propTypes = { avatar: PropTypes.string, size: PropTypes.number, locked: PropTypes.bool };
