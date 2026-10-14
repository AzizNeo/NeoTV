import { defineMessages, useTranslation } from '@/core/i18n';

export const messages = defineMessages('devices', {
  tr: {
    nav: {
      devices: 'Cihazlar',
    },
  },
  en: {
    nav: {
      devices: 'Devices',
    },
  },
});

export const useT = () => useTranslation(messages);
