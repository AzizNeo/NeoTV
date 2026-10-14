import { defineMessages, useTranslation } from '@/core/i18n';

export const messages = defineMessages('catalog', {
  tr: {
    nav: { home: 'Ana Sayfa' },
    loadFailed: 'Katalog yüklenemedi',
    retry: 'Tekrar dene',
    empty: 'Kütüphane boş',
    emptyBody: 'Yönetici bir oynatma listesi eklediğinde içerikler burada görünür.',
    liveChannels: 'Canlı kanallar',
    channels: { other: '{count} kanal' },
    items: { other: '{count} içerik' },
  },
  en: {
    nav: { home: 'Home' },
    loadFailed: "The catalogue couldn't be loaded",
    retry: 'Try again',
    empty: 'The library is empty',
    emptyBody: 'Content shows up here once an administrator adds a playlist.',
    liveChannels: 'Live channels',
    channels: { one: '{count} channel', other: '{count} channels' },
    items: { one: '{count} item', other: '{count} items' },
  },
});

export const useT = () => useTranslation(messages);
