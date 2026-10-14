import { defineMessages, useTranslation } from '@/core/i18n';

export const messages = defineMessages('library', {
  tr: {
    nav: { favorites: 'Favoriler', history: 'Geçmiş' },
    continue: 'İzlemeye devam et',
    favorites: {
      title: 'Favorilerim',
      count: { other: '{count} içerik' },
      empty: 'Henüz favoriniz yok',
      emptyBody: 'Bir içeriğin altındaki kalp simgesine dokunarak favorilere ekleyebilirsiniz.',
      add: '{title} favorilere ekle',
      remove: '{title} favorilerden çıkar',
    },
    history: {
      title: 'İzleme geçmişi',
      recent: 'Son izlenenler',
      clear: 'Geçmişi temizle',
      cleared: { other: '{count} kayıt silindi.' },
      empty: 'Geçmiş boş',
      emptyBody: 'İzlediğiniz içerikler burada listelenir.',
      minutes: '{n} dk',
      seconds: '{n} sn',
    },
  },
  en: {
    nav: { favorites: 'Favourites', history: 'History' },
    continue: 'Continue watching',
    favorites: {
      title: 'My favourites',
      count: { one: '{count} item', other: '{count} items' },
      empty: 'No favourites yet',
      emptyBody: 'Tap the heart under any title to add it to your favourites.',
      add: 'Add {title} to favourites',
      remove: 'Remove {title} from favourites',
    },
    history: {
      title: 'Watch history',
      recent: 'Recently watched',
      clear: 'Clear history',
      cleared: { one: '{count} entry deleted.', other: '{count} entries deleted.' },
      empty: 'No history yet',
      emptyBody: 'What you watch is listed here.',
      minutes: '{n} min',
      seconds: '{n} s',
    },
  },
});

export const useT = () => useTranslation(messages);
