import { defineMessages, useTranslation } from '@/core/i18n';

export const messages = defineMessages('recommendations', {
  tr: {
    rows: { forYou: 'Senin için', trending: 'Şu an popüler', because: '{title} izlediğiniz için' },
    reasons: { trending: 'Popüler', recommended: 'Önerilen', likes_group: '{subject} sevdiğiniz için', watched: '{subject} izlediğiniz için' },
  },
  en: {
    rows: { forYou: 'For you', trending: 'Trending now', because: 'Because you watched {title}' },
    reasons: { trending: 'Trending', recommended: 'Recommended', likes_group: 'Because you like {subject}', watched: 'Because you watched {subject}' },
  },
});

export const useT = () => useTranslation(messages);
