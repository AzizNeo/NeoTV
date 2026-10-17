import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';
import { readSecurityHeaders } from './scripts/security-headers.mjs';
import pkg from './package.json' with { type: 'json' };

const API_TARGET = process.env.VITE_DEV_API_TARGET ?? 'http://127.0.0.1:5000';

export default defineConfig({
  plugins: [react()],
  // The release reported with browser errors (which build threw it).
  define: { __NEOTV_RELEASE__: JSON.stringify(pkg.version) },
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  server: {
    // Same-origin in dev: the refresh cookie (SameSite=Strict, path /api/v1/auth)
    // and signed media URLs work exactly as behind the production nginx.
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: false, secure: false },
    },
  },
  // `npm run preview` = the production build under the production headers (CSP included). The dev
  // server stays without CSP: Vite's hot reload injects inline scripts the policy rightly forbids.
  preview: {
    headers: readSecurityHeaders(),
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: false, secure: false },
    },
  },
  build: {
    sourcemap: true,
    // Fonts stay files: inlined as data: URIs they would need `font-src data:` in the CSP.
    assetsInlineLimit: (file) => (/\.(woff2?|ttf|otf)$/i.test(file) ? false : undefined),
    // The only chunks above Vite's 500 kB default are the player engines (hls.js,
    // and shaka which is lazy-loaded for EME DRM only). App code stays far below.
    chunkSizeWarningLimit: 800,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          query: ['@tanstack/react-query'],
          hls: ['hls.js'],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.{js,jsx}'], // e2e/*.spec.js belong to Playwright (npm run e2e)
    setupFiles: ['./src/test/setup.js'],
    css: { modules: { classNameStrategy: 'non-scoped' } },
    // `npm run coverage` (CI). Floors are a ratchet: raise them as tests grow, never lower them.
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{js,jsx}'],
      exclude: ['src/**/*.test.{js,jsx}', 'src/test/**', 'src/core/api/contract.generated.js', 'src/main.jsx'],
      reporter: ['text-summary', 'json-summary', 'html'],
      reportsDirectory: 'coverage',
      thresholds: { statements: 26, branches: 20, functions: 17, lines: 26 },
    },
  },
});
