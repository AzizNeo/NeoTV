import { useEffect, useRef } from 'react';
import { api } from '@/core/api/client';
import { useAuth } from '@/core/auth/AuthProvider';
import { hasChosenLocale, setLocale, useLocale } from '@/core/i18n';

/**
 * One language per account, on every device — and the one its e-mails are written in.
 *
 * On sign-in: a device where nobody picked a language adopts the account's; a device where the
 * viewer did pick one (even on the sign-in screen) tells the account. Afterwards every switch is
 * saved to the account (best effort: offline or rate-limited, the device still switches).
 */
export function LocaleSync() {
  const { user, isAuthenticated } = useAuth();
  const { locale } = useLocale();
  const reconciled = useRef(null); // user id whose stored language we already reconciled
  const saved = useRef(null); // what the server has for that user, as far as we know

  useEffect(() => {
    if (!isAuthenticated || !user) {
      reconciled.current = null;
      return;
    }
    if (reconciled.current !== user.id) {
      reconciled.current = user.id;
      saved.current = user.locale ?? null;
      if (user.locale && !hasChosenLocale() && user.locale !== locale) {
        setLocale(user.locale); // this effect runs again with the adopted language — nothing to save
        return;
      }
    }
    if (saved.current === locale) return;
    saved.current = locale;
    api.call('identity_set_locale', { body: { locale } }).catch(() => {
      saved.current = null; // retry on the next switch
    });
  }, [isAuthenticated, user, locale]);

  return null;
}
