import { defineMessages, useTranslation } from '@/core/i18n';

export const messages = defineMessages('auth', {
  tr: {
    nav: {
      account: 'Hesap',
    },
  },
  en: {
    nav: {
      account: 'Account',
    },
  },
});

export const useT = () => useTranslation(messages);
