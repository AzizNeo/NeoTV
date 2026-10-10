import { useMemo } from 'react';
import { RouterProvider } from 'react-router-dom';
import { AppProviders } from './AppProviders';
import { createAppRouter } from './createAppRouter';

export function App({ registry }) {
  const router = useMemo(() => createAppRouter(registry), [registry]);
  return (
    <AppProviders>
      <RouterProvider router={router} />
    </AppProviders>
  );
}
