import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '@/core/auth/AuthProvider';
import { Slot, useRegistry } from '@/core/featureKit';
import { labelOf } from '@/core/i18n';
import { useT } from './i18n';
import { AccountMenu } from './AccountMenu';
import styles from './AppShell.module.css';

const TABBAR_MAX = 5; // thumb-reachable bottom bar on phones; the rest stays in the top bar / account menu

/**
 * App frame built purely from feature manifests (`nav`) — no hard-coded links.
 * Desktop: top bar (main section) + account menu (account section). Phone: bottom tab bar.
 */
export function AppShell() {
  const { nav } = useRegistry();
  const { can } = useAuth();
  const t = useT();
  const visible = nav.filter((item) => item.guard !== 'admin' || can('admin:access'));
  const main = visible.filter((item) => item.section === 'main');
  const account = visible.filter((item) => item.section === 'account');

  const link = ({ to, label, icon: Icon, feature }, className) => (
    <NavLink key={`${feature}:${to}`} to={to} end={to === '/'} className={({ isActive }) => `${className} ${isActive ? styles.active : ''}`}>
      <Icon size={20} aria-hidden="true" className={styles.icon} />
      <span>{labelOf(label, t.locale)}</span>
    </NavLink>
  );

  return (
    <div className={styles.shell}>
      <a href="#main" className={styles.skip}>{t('skip')}</a>
      <header className={styles.topbar}>
        <NavLink to="/" className={styles.brand} aria-label={t('home')}>
          <span className={styles.lamp} aria-hidden="true" />
          NeoTV
        </NavLink>
        <nav className={styles.primary} aria-label={t('mainNav')}>
          {main.map((item) => link(item, styles.navLink))}
        </nav>
        <div className={styles.tools}>
          <Slot name="shell.actions" />
          <AccountMenu items={account} overflow={main.slice(TABBAR_MAX)} />
        </div>
      </header>
      <main id="main" className={styles.main} tabIndex={-1}>
        <Outlet />
      </main>
      <nav className={styles.tabbar} aria-label={t('mobileNav')}>
        {main.slice(0, TABBAR_MAX).map((item) => link(item, styles.tab))}
      </nav>
    </div>
  );
}
