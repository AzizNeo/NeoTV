import { useEffect, useMemo } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from '@/core/api/queryClient';
import { subscribeLocale } from '@/core/i18n';
import { AuthProvider } from '@/core/auth/AuthProvider';
import { ThemeProvider } from '@/core/theme/ThemeProvider';
import { SharedTextProvider } from '@/shared/components/SharedText/SharedTextProvider';
import { ToastProvider } from '@/shared/components/Toast/Toast';
import { useT } from './i18n';
import { LocaleSync } from './LocaleSync';

/** The words shared components say, in the current language (shared/ itself stays i18n-free). */
function SharedText({ children }) {
  const t = useT();
  const value = useMemo(
    () => ({ live: t('shared.live'), close: t('shared.close'), playItem: (title) => t('shared.playItem', { title }) }),
    [t],
  );
  return <SharedTextProvider value={value}>{children}</SharedTextProvider>;
}

/**
 * Server text (titles, synopses, genres …) is answered in the request's language (Accept-Language):
 * after a switch every cached answer is in the old one, so refetch what is on screen.
 */
function RefetchOnLanguageChange() {
  useEffect(() => subscribeLocale(() => queryClient.invalidateQueries()), []);
  return null;
}

/** App-wide, router-independent providers. Feature providers live inside the router (RootLayout). */
export function AppProviders({ children }) {
  return (
    <ThemeProvider>
      <SharedText>
        <QueryClientProvider client={queryClient}>
          <RefetchOnLanguageChange />
          <ToastProvider>
            <AuthProvider>
              <LocaleSync />
              {children}
            </AuthProvider>
          </ToastProvider>
        </QueryClientProvider>
      </SharedText>
    </ThemeProvider>
  );
}
