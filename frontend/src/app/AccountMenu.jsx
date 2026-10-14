import { useEffect, useId, useRef, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { ChevronDown, Languages, LogOut, Monitor, Moon, Sun, UserRound } from 'lucide-react';
import { useAuth } from '@/core/auth/AuthProvider';
import { Slot, useSlot } from '@/core/featureKit';
import { labelOf, useLocale } from '@/core/i18n';
import { useTheme } from '@/core/theme/ThemeProvider';
import { useT } from './i18n';
import styles from './AppShell.module.css';

const THEMES = [
  { id: 'system', icon: Monitor },
  { id: 'dark', icon: Moon },
  { id: 'light', icon: Sun },
];

/**
 * Profile / account menu (disclosure pattern): who is watching, account pages from the feature
 * manifests (`section: 'account'`), theme, language and sign-out. Closes on Escape, outside click and navigation.
 */
export function AccountMenu({ items, overflow = [] }) {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const { locale, setLocale, locales } = useLocale();
  const t = useT();
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
        aria-label={t('account.menu')}
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
          {overflow.length > 0 && (
            // Phone only: main-menu items that do not fit the bottom tab bar.
            <nav aria-label={t('account.more')} className={`${styles.menuLinks} ${styles.menuOverflow}`}>
              {overflow.map(({ to, label, icon: Icon, feature }) => (
                <NavLink key={`${feature}:${to}`} to={to} className={({ isActive }) => (isActive ? styles.menuLinkActive : styles.menuLink)}>
                  <Icon size={18} aria-hidden="true" /> {labelOf(label, locale)}
                </NavLink>
              ))}
            </nav>
          )}
          {items.length > 0 && (
            <nav aria-label={t('account.section')} className={styles.menuLinks}>
              {items.map(({ to, label, icon: Icon, feature }) => (
                <NavLink key={`${feature}:${to}`} to={to} className={({ isActive }) => (isActive ? styles.menuLinkActive : styles.menuLink)}>
                  <Icon size={18} aria-hidden="true" /> {labelOf(label, locale)}
                </NavLink>
              ))}
            </nav>
          )}
          <fieldset className={styles.theme}>
            <legend>{t('account.theme')}</legend>
            <div className={styles.themeOptions}>
              {THEMES.map(({ id, icon: Icon }) => (
                <label key={id} className={theme === id ? styles.themeOptionActive : styles.themeOption}>
                  <input type="radio" name="theme" value={id} checked={theme === id} onChange={() => setTheme(id)} className="visually-hidden" />
                  <Icon size={16} aria-hidden="true" /> {t(`account.themes.${id}`)}
                </label>
              ))}
            </div>
          </fieldset>
          <fieldset className={styles.theme}>
            <legend>
              <Languages size={14} aria-hidden="true" /> {t('account.language')}
            </legend>
            <div className={styles.themeOptions}>
              {Object.entries(locales).map(([id, name]) => (
                <label key={id} className={locale === id ? styles.themeOptionActive : styles.themeOption} lang={id}>
                  <input type="radio" name="locale" value={id} checked={locale === id} onChange={() => setLocale(id)} className="visually-hidden" />
                  {name}
                </label>
              ))}
            </div>
          </fieldset>
          <button type="button" className={styles.signOut} onClick={() => { close(); logout(); }}>
            <LogOut size={18} aria-hidden="true" /> {user?.username ? t('account.signOutAs', { name: user.username }) : t('account.signOut')}
          </button>
        </div>
      )}
    </div>
  );
}
