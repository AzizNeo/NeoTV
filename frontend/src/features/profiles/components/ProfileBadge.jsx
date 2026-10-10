import { Link } from 'react-router-dom';
import { Avatar } from './Avatar';
import { useProfile } from './ProfileProvider';

/** Contribution to the shell's `shell.user` slot: who is watching + switch link. */
export function ProfileBadge() {
  const { current } = useProfile();
  if (!current) return null;
  return (
    <Link to="/profiles" title="Profil değiştir" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'inherit', textDecoration: 'none' }}>
      <Avatar avatar={current.avatar} size={32} />
      <span>{current.name}</span>
    </Link>
  );
}
