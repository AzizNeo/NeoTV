import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '@/core/api/queryClient';
import { AuthProvider } from '@/core/auth/AuthProvider';
import { ToastProvider } from '@/shared/components/Toast/Toast';

/** App-wide, router-independent providers. Feature providers live inside the router (RootLayout). */
export function AppProviders({ children }) {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <AuthProvider>{children}</AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}
