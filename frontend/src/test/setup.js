import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeEach } from 'vitest';
import { setLocale } from '@/core/i18n';

// Tests read the Turkish UI (the default language), whatever jsdom's navigator.language says.
beforeEach(() => setLocale('tr'));
afterEach(() => cleanup());

// jsdom has no matchMedia; ThemeProvider (and the boot script) query it.
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    addEventListener() {},
    removeEventListener() {},
    onchange: null,
  });
}
