import { defineMessages, useTranslation } from '@/core/i18n';

export const messages = defineMessages('catalog', {
  tr: {
    nav: {
      home: 'Ana Sayfa',
    },
  },
  en: {
    nav: {
      home: 'Home',
    },
  },
});

export const useT = () => useTranslation(messages);
