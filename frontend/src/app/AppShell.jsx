import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { LogOut, Menu, Tv, X } from 'lucide-react';
import { useAuth } from '@/core/auth/AuthProvider';
import { Slot, useRegistry } from '@/core/featureKit';
import styles from './AppShell.module.css';

const SECTIONS = [['main', null], ['account', 'Hesap']];

/** Sidebar navigation built purely from feature manifests (`nav`) — no hard-coded links. */
export function AppShell() {
  const { nav } = useRegistry();
  const { can, user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const visible = nav.filter((item) => item.guard !== 'admin' || can('admin:access'));

  return (
    <div className={styles.shell}>
      <button type="button" className={styles.menuButton} onClick={() => setOpen((o) => !o)} aria-label="Menü" aria-expanded={open}>
        {open ? <X size={22} /> : <Menu size={22} />}
      </button>
      <aside className={`${styles.sidebar} ${open ? styles.open : ''}`}>
        <NavLink to="/" className={styles.brand} onClick={() => setOpen(false)}>
          <Tv size={24} aria-hidden="true" /> NeoTV
        </NavLink>
        <div className={styles.user}><Slot name="shell.user" /></div>
        {SECTIONS.map(([section, title]) => {
          const items = visible.filter((item) => item.section === section);
          if (!items.length) return null;
          return (
            <nav key={section} className={styles.nav} aria-label={title ?? 'Ana menü'}>
              {title && <span className={styles.sectionTitle}>{title}</span>}
              {items.map(({ to, label, icon: Icon, feature }) => (
                <NavLink key={`${feature}:${to}`} to={to} end={to === '/'} onClick={() => setOpen(false)}
                  className={({ isActive }) => `${styles.link} ${isActive ? styles.active : ''}`}>
                  <Icon size={18} aria-hidden="true" /> {label}
                </NavLink>
              ))}
            </nav>
          );
        })}
        <button type="button" className={styles.logout} onClick={() => logout()}>
          <LogOut size={18} aria-hidden="true" /> Çıkış {user?.username ? `(${user.username})` : ''}
        </button>
      </aside>
      <main className={styles.main}><Outlet /></main>
    </div>
  );
}
