import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

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
