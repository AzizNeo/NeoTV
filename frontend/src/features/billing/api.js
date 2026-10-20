import { api } from '@/core/api/client';
import { formatDate, formatMoney } from '@/core/i18n';

export const billingKeys = { plans: ['billing', 'plans'], subscription: ['billing', 'subscription'] };

export const getPlans = () => api.call('billing_plans');
export const getSubscription = () => api.call('billing_subscription');

/** Price in the viewer's language: "Ücretsiz" / "Free", "₺29,99" / "TRY 29.99". */
export const money = (minor, currency, t) => (minor === 0 ? t('free') : formatMoney(minor, currency, t.locale));
export const date = (iso, t) => formatDate(iso, {}, t.locale);

const STATUSES = new Set(['trial', 'active', 'grace', 'cancelled', 'expired', 'suspended']);
export const statusText = (status, t) => (STATUSES.has(status) ? t(`status.${status}`) : status);

const quality = (resolution) => {
  const height = Number.parseInt(resolution, 10) || 0;
  return height >= 2160 ? 'uhd' : height >= 1080 ? 'fhd' : height >= 720 ? 'hd' : 'sd';
};

/**
 * A plan's bullet points, derived from its entitlements — the limits the server enforces — so
 * what the card promises can never drift from what the plan allows, in any language.
 */
export function perks(e, t) {
  return [
    t('perks.screens', { count: e.max_streams }),
    t(`perks.quality.${quality(e.max_resolution)}`),
    t(e.ads ? 'perks.ads' : 'perks.noAds'),
    e.offline_downloads && t('perks.downloads'),
    e.max_profiles > 1 && t('perks.profiles', { count: e.max_profiles }),
    e.catchup_days > 0 && t('perks.catchup', { count: e.catchup_days }),
  ].filter(Boolean);
}
