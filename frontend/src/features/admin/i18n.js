import { defineMessages, useTranslation } from '@/core/i18n';

export const messages = defineMessages('admin', {
  tr: {
    nav: {
      admin: 'Yönetim',
    },
  },
  en: {
    nav: {
      admin: 'Admin',
    },
  },
});

export const useT = () => useTranslation(messages);
