import { Suspense } from 'react';
import { NavLink, Navigate, Route, Routes } from 'react-router-dom';
import { useRegistry } from '@/core/featureKit';
import { ErrorBoundary } from '@/shared/components/ErrorBoundary/ErrorBoundary';
import { Page } from '@/shared/components/Page/Page';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { ADMIN_SECTIONS } from '../sections/registry';
import styles from '../components/Admin.module.css';
import { labelOf } from '@/core/i18n';
import { useT } from '../i18n';
import { ADMIN_BASE, adminPath } from '../paths';

export default function AdminPage() {
  const t = useT();
  const { backendModules } = useRegistry();
  // One broken section never takes the whole panel down (and says so in the viewer's language).
  const errorLabels = { title: t('boundary.title'), unknown: t('boundary.unknown'), reload: t('boundary.reload') };
  const sections = ADMIN_SECTIONS.filter((s) => !backendModules || backendModules.has(s.module));
  return (
    <Page title={t('title')} subtitle={t('subtitle')}>
      <nav className={styles.tabs} aria-label={t('sectionsNav')}>
        {sections.map(({ id, label, icon: Icon }) => (
          <NavLink key={id} to={adminPath(id)} className={({ isActive }) => `${styles.tab} ${isActive ? styles.active : ''}`}>
            <Icon size={16} aria-hidden="true" /> {labelOf(label, t.locale)}
          </NavLink>
        ))}
      </nav>
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route index element={<Navigate to={adminPath(sections[0]?.id ?? 'overview')} replace />} />
          {sections.map(({ id, component: Section }) => (
            <Route key={id} path={id} element={<ErrorBoundary resetKey={id} labels={errorLabels}><Section /></ErrorBoundary>} />
          ))}
          <Route path="*" element={<Navigate to={ADMIN_BASE} replace />} />
        </Routes>
      </Suspense>
    </Page>
  );
}
