import { defineMessages, useTranslation } from '@/core/i18n';

export const messages = defineMessages('titles', {
  tr: {
    nav: {
      browse: 'Keşfet',
    },
  },
  en: {
    nav: {
      browse: 'Browse',
    },
  },
});

export const useT = () => useTranslation(messages);
