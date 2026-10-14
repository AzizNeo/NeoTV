import { defineMessages, useTranslation } from '@/core/i18n';

export const messages = defineMessages('library', {
  tr: {
    nav: {
      favorites: 'Favoriler',
      history: 'Geçmiş',
    },
  },
  en: {
    nav: {
      favorites: 'Favourites',
      history: 'History',
    },
  },
});

export const useT = () => useTranslation(messages);
