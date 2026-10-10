import { api } from '@/core/api/client';

export const billingKeys = { plans: ['billing', 'plans'], subscription: ['billing', 'subscription'] };

export const getPlans = () => api.call('billing_plans');
export const getSubscription = () => api.call('billing_subscription');

export const money = (minor, currency) =>
  minor === 0 ? 'Ücretsiz' : new Intl.NumberFormat('tr-TR', { style: 'currency', currency }).format(minor / 100);

export const date = (iso) => (iso ? new Date(iso).toLocaleDateString('tr-TR', { dateStyle: 'long' }) : null);

export const STATUS_TEXT = {
  trial: 'Deneme süresinde',
  active: 'Aktif',
  grace: 'Ödeme bekleniyor',
  cancelled: 'İptal edildi (dönem sonuna kadar geçerli)',
  expired: 'Sona erdi',
  suspended: 'Askıda',
};
