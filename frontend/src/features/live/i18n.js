import { defineMessages, useTranslation } from '@/core/i18n';

export const messages = defineMessages('live', {
  tr: {
    nav: { live: 'Canlı TV' },
    title: 'Canlı TV',
    subtitle: 'Şu an yayında olanlar ve yayın akışı',
    channelsRow: 'Kanallar',
    empty: 'Canlı kanal yok',
    emptyBody: 'Yönetici canlı kanal eklediğinde burada görünecek.',
    searchRow: 'Canlı yayınlar',
    channels: { other: '{count} kanal' },
    nowNext: '{time} {now} · Sonra: {next}',
    now: '{time} {now}',
    guide: 'Yayın akışı',
    watch: '{name} izle',
    startOver: '{title} ({channel}) — baştan başlat',
    catchup: '{title} ({channel}, {time}) — tekrar izle',
  },
  en: {
    nav: { live: 'Live TV' },
    title: 'Live TV',
    subtitle: 'On air now, and the programme guide',
    channelsRow: 'Channels',
    empty: 'No live channels',
    emptyBody: 'Channels show up here once an administrator adds them.',
    searchRow: 'Live broadcasts',
    channels: { one: '{count} channel', other: '{count} channels' },
    nowNext: '{time} {now} · Next: {next}',
    now: '{time} {now}',
    guide: 'Programme guide',
    watch: 'Watch {name}',
    startOver: '{title} ({channel}) — start over',
    catchup: '{title} ({channel}, {time}) — watch again',
  },
});

export const useT = () => useTranslation(messages);
