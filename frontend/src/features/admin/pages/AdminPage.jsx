import { Suspense } from 'react';
import { NavLink, Navigate, Route, Routes } from 'react-router-dom';
import { useRegistry } from '@/core/featureKit';
import { ErrorBoundary } from '@/shared/components/ErrorBoundary/ErrorBoundary';
import { Page } from '@/shared/components/Page/Page';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { ADMIN_SECTIONS } from '../sections/registry';
import styles from '../components/Admin.module.css';

export default function AdminPage() {
  const { backendModules } = useRegistry();
  const sections = ADMIN_SECTIONS.filter((s) => !backendModules || backendModules.has(s.module));
  return (
    <Page title="Yönetim" subtitle="Platform durumu, kullanıcılar, içerik ve koruma.">
      <nav className={styles.tabs} aria-label="Yönetim bölümleri">
        {sections.map(({ id, label, icon: Icon }) => (
          <NavLink key={id} to={id} className={({ isActive }) => `${styles.tab} ${isActive ? styles.active : ''}`}>
            <Icon size={16} aria-hidden="true" /> {label}
          </NavLink>
        ))}
      </nav>
      <Suspense fallback={<Spinner />}>
        <Routes>
          <Route index element={<Navigate to={sections[0]?.id ?? 'overview'} replace />} />
          {sections.map(({ id, component: Section }) => (
            <Route key={id} path={id} element={<ErrorBoundary resetKey={id}><Section /></ErrorBoundary>} />
          ))}
          <Route path="*" element={<Navigate to="." replace />} />
        </Routes>
      </Suspense>
    </Page>
  );
}
