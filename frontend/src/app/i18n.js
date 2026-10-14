import { defineMessages, useTranslation } from '@/core/i18n';

export const messages = defineMessages('app', {
  tr: {
    skip: 'İçeriğe geç',
    home: 'NeoTV ana sayfa',
    mainNav: 'Ana menü',
    mobileNav: 'Ana menü (mobil)',
    account: {
      menu: 'Hesap menüsü',
      more: 'Diğer',
      section: 'Hesap',
      theme: 'Tema',
      themes: { system: 'Sistem', dark: 'Koyu', light: 'Açık' },
      language: 'Dil',
      signOut: 'Çıkış yap',
      signOutAs: 'Çıkış yap ({name})',
    },
    error: { title: 'Bir şeyler ters gitti.', unknown: 'Beklenmeyen bir arayüz hatası oluştu.', reload: 'Sayfayı yenile' },
    notFound: { title: 'Sayfa bulunamadı', body: 'Aradığınız sayfa taşınmış ya da hiç var olmamış olabilir.', back: 'Ana sayfaya dön' },
    boot: { hint: 'src/features/index.js, manifest dosyaları veya VITE_DISABLED_FEATURES değerini kontrol edin.' },
    shared: { live: 'Canlı', close: 'Kapat', playItem: '{title} oynat' },
  },
  en: {
    skip: 'Skip to content',
    home: 'NeoTV home',
    mainNav: 'Main menu',
    mobileNav: 'Main menu (mobile)',
    account: {
      menu: 'Account menu',
      more: 'More',
      section: 'Account',
      theme: 'Theme',
      themes: { system: 'System', dark: 'Dark', light: 'Light' },
      language: 'Language',
      signOut: 'Sign out',
      signOutAs: 'Sign out ({name})',
    },
    error: { title: 'Something went wrong.', unknown: 'An unexpected interface error occurred.', reload: 'Reload page' },
    notFound: { title: 'Page not found', body: 'The page you are looking for may have moved or never existed.', back: 'Back to home' },
    boot: { hint: 'Check src/features/index.js, the manifest files or VITE_DISABLED_FEATURES.' },
    shared: { live: 'Live', close: 'Close', playItem: 'Play {title}' },
  },
});

export const useT = () => useTranslation(messages);
