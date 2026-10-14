import { Link } from 'react-router-dom';
import { Avatar } from './Avatar';
import { useProfile } from './ProfileProvider';
import styles from './Avatar.module.css';
import { useT } from '../i18n';

/**
 * Contribution to the shell's `shell.user` slot: who is watching.
 * `compact` (the account-menu trigger) renders only the avatar — the trigger is a button, so no link inside it.
 */
export function ProfileBadge({ compact = false }) {
  const t = useT();
  const { current } = useProfile();
  if (!current) return null;
  if (compact) return <Avatar avatar={current.avatar} size={32} />;
  return (
    <Link to="/profiles" className={styles.badge}>
      <Avatar avatar={current.avatar} size={40} />
      <span className={styles.badgeText}>
        <strong>{current.name}</strong>
        <span>{t('switch')}</span>
      </span>
    </Link>
  );
}
