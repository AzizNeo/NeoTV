import { defineMessages, useTranslation } from '@/core/i18n';

export const messages = defineMessages('live', {
  tr: {
    nav: {
      live: 'Canlı TV',
    },
  },
  en: {
    nav: {
      live: 'Live TV',
    },
  },
});

export const useT = () => useTranslation(messages);
