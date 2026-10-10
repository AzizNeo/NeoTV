import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath, URL } from 'node:url';

const API_TARGET = process.env.VITE_DEV_API_TARGET ?? 'http://127.0.0.1:5000';

export default defineConfig({
  plugins: [react()],
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
  build: {
    sourcemap: true,
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
    setupFiles: ['./src/test/setup.js'],
    css: { modules: { classNameStrategy: 'non-scoped' } },
  },
});
