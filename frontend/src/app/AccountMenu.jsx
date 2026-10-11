import { useEffect, useId, useRef, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { ChevronDown, LogOut, Monitor, Moon, Sun, UserRound } from 'lucide-react';
import { useAuth } from '@/core/auth/AuthProvider';
import { Slot, useSlot } from '@/core/featureKit';
import { useTheme } from '@/core/theme/ThemeProvider';
import styles from './AppShell.module.css';

const THEMES = [
  { id: 'system', label: 'Sistem', icon: Monitor },
  { id: 'dark', label: 'Koyu', icon: Moon },
  { id: 'light', label: 'Açık', icon: Sun },
];

/**
 * Profile / account menu (disclosure pattern): who is watching, account pages from the feature
 * manifests (`section: 'account'`), theme and sign-out. Closes on Escape, outside click and navigation.
 */
export function AccountMenu({ items }) {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const hasProfile = useSlot('shell.user').length > 0;
  const { pathname } = useLocation();
  // Open *on this page*: navigating anywhere closes it without an effect.
  const [openOn, setOpenOn] = useState(null);
  const open = openOn === pathname;
  const close = () => setOpenOn(null);
  const panelId = useId();
  const root = useRef(null);
  const trigger = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') {
        setOpenOn(null);
        trigger.current?.focus();
      }
    };
    const onPointer = (e) => {
      if (!root.current?.contains(e.target)) setOpenOn(null);
    };
    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [open]);

  return (
    <div className={styles.account} ref={root}>
      <button
        ref={trigger}
        type="button"
        className={styles.accountTrigger}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label="Hesap menüsü"
        onClick={() => setOpenOn(open ? null : pathname)}
      >
        {hasProfile ? <Slot name="shell.user" compact /> : <UserRound size={20} aria-hidden="true" />}
        <ChevronDown size={16} aria-hidden="true" className={open ? styles.chevronOpen : styles.chevron} />
      </button>

      {open && (
        <div id={panelId} className={styles.menu}>
          {hasProfile && (
            <div className={styles.menuProfile}>
              <Slot name="shell.user" />
            </div>
          )}
          {items.length > 0 && (
            <nav aria-label="Hesap" className={styles.menuLinks}>
              {items.map(({ to, label, icon: Icon, feature }) => (
                <NavLink key={`${feature}:${to}`} to={to} className={({ isActive }) => (isActive ? styles.menuLinkActive : styles.menuLink)}>
                  <Icon size={18} aria-hidden="true" /> {label}
                </NavLink>
              ))}
            </nav>
          )}
          <fieldset className={styles.theme}>
            <legend>Tema</legend>
            <div className={styles.themeOptions}>
              {THEMES.map(({ id, label, icon: Icon }) => (
                <label key={id} className={theme === id ? styles.themeOptionActive : styles.themeOption}>
                  <input type="radio" name="theme" value={id} checked={theme === id} onChange={() => setTheme(id)} className="visually-hidden" />
                  <Icon size={16} aria-hidden="true" /> {label}
                </label>
              ))}
            </div>
          </fieldset>
          <button type="button" className={styles.signOut} onClick={() => { close(); logout(); }}>
            <LogOut size={18} aria-hidden="true" /> Çıkış yap{user?.username ? ` (${user.username})` : ''}
          </button>
        </div>
      )}
    </div>
  );
}
