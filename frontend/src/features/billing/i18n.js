import { defineMessages, useTranslation } from '@/core/i18n';

export const messages = defineMessages('billing', {
  tr: {
    nav: {
      plans: 'Premium',
    },
  },
  en: {
    nav: {
      plans: 'Premium',
    },
  },
});

export const useT = () => useTranslation(messages);
