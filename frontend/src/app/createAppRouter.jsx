import { createBrowserRouter, Outlet, useLocation } from 'react-router-dom';
import { RedirectIfAuthenticated, RequireAuth, RequirePermission } from '@/core/auth/guards';
import { RegistryProvider } from '@/core/featureKit';
import { ErrorBoundary } from '@/shared/components/ErrorBoundary/ErrorBoundary';
import { AppShell } from './AppShell';
import { useT } from './i18n';
import NotFound from './NotFound';

/** Feature providers need the router (navigation), so they wrap the route tree here. */
function RootLayout({ registry }) {
  const location = useLocation();
  const t = useT();
  const tree = registry.providers.reduceRight((children, Provider) => <Provider>{children}</Provider>, <Outlet />);
  return (
    <RegistryProvider registry={registry}>
      <ErrorBoundary resetKey={location.pathname} labels={{ title: t('error.title'), unknown: t('error.unknown'), reload: t('error.reload') }}>
        {tree}
      </ErrorBoundary>
    </RegistryProvider>
  );
}

const LAYOUT = { shell: <AppShell />, bare: <Outlet /> };
const GUARD = {
  public: <RedirectIfAuthenticated />,
  any: <Outlet />,
  auth: <RequireAuth />,
  admin: <RequireAuth />, // + RequirePermission one level down
};

const toRoute = (def) => ({
  path: def.path,
  lazy: async () => {
    const module = await def.lazy();
    if (!module.default) throw new Error(`[feature:${def.feature}] route ${def.path} has no default export`);
    return { Component: module.default };
  },
});

function layoutGroups(routes) {
  return Object.entries(LAYOUT)
    .map(([layout, element]) => ({ element, children: routes.filter((r) => r.layout === layout).map(toRoute) }))
    .filter((group) => group.children.length);
}

/** Routes are grouped guard → layout so each guard/layout renders once per navigation. */
export function buildRouteTree(registry) {
  const byGuard = (guard) => registry.routes.filter((r) => r.guard === guard);
  const authGroups = layoutGroups(byGuard('auth'));
  authGroups.push({ element: <AppShell />, children: [{ path: '*', element: <NotFound /> }] });
  return [
    {
      element: <RootLayout registry={registry} />,
      children: [
        { element: GUARD.public, children: layoutGroups(byGuard('public')) },
        { element: GUARD.any, children: layoutGroups(byGuard('any')) },
        { element: GUARD.auth, children: authGroups },
        { element: GUARD.admin, children: [{ element: <RequirePermission permission="admin:access" />, children: layoutGroups(byGuard('admin')) }] },
      ],
    },
  ];
}

export const createAppRouter = (registry) => createBrowserRouter(buildRouteTree(registry));
