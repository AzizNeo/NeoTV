import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { Spinner } from '@/shared/components/Spinner/Spinner';
import { useAuth } from './AuthProvider';

export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();
  if (status === 'loading') return <Spinner fullScreen />;
  if (status !== 'authenticated') return <Navigate to="/login" replace state={{ from: location }} />;
  return <Outlet />;
}

/** Back-office routes: the backend enforces permissions; this only avoids dead ends. */
export function RequirePermission({ permission = 'admin:access' }) {
  const { can } = useAuth();
  return can(permission) ? <Outlet /> : <Navigate to="/" replace />;
}

export function RedirectIfAuthenticated() {
  const { status } = useAuth();
  const location = useLocation();
  if (status === 'loading') return <Spinner fullScreen />;
  if (status === 'authenticated') return <Navigate to={location.state?.from?.pathname ?? '/'} replace />;
  return <Outlet />;
}
