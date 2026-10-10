import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import { defineConfig, globalIgnores } from 'eslint/config';

/*
 * Layer rules (the frontend half of the puzzle):
 *   app/      composition root — may import everything
 *   features/ may import core/, shared/ and ANOTHER feature only via its index.js
 *   core/     infrastructure — never imports features/ or app/
 *   shared/   presentational building blocks — never imports features/, app/ or core/
 */
const featureInternals = {
  group: ['@/features/*/*', '@/features/*/**', '../../*/**', '../../../features/**'],
  message: 'Import another feature only through its public index.js (e.g. "@/features/player").',
};

export default defineConfig([
  globalIgnores(['dist', 'coverage', 'src/core/api/contract.generated.js']),
  {
    files: ['**/*.{js,jsx,mjs}'],
    extends: [js.configs.recommended, reactHooks.configs.flat.recommended, reactRefresh.configs.vite],
    languageOptions: {
      ecmaVersion: 'latest',
      globals: { ...globals.browser, ...globals.node },
      parserOptions: { ecmaFeatures: { jsx: true }, sourceType: 'module' },
    },
    rules: {
      // Capitalised names are JSX components (`icon: Icon`), which core ESLint cannot see being used.
      'no-unused-vars': ['error', { varsIgnorePattern: '^[A-Z_]', argsIgnorePattern: '^(_|[A-Z])' }],
      'no-console': ['error', { allow: ['warn', 'error'] }],
    },
  },
  {
    // Context modules deliberately co-locate <Provider> with its hook (useX); the
    // router module exports a factory. Fast-refresh falls back to a full reload there.
    files: ['src/core/**/*.jsx', 'src/**/*Provider.jsx', 'src/shared/components/Toast/Toast.jsx', 'src/app/createAppRouter.jsx'],
    rules: { 'react-refresh/only-export-components': 'off' },
  },
  {
    files: ['src/features/**/*.{js,jsx}'],
    rules: {
      'no-restricted-imports': ['error', { patterns: [featureInternals, { group: ['@/app/*', '@/app/**'], message: 'features must not import the composition root (contracts live in @/core)' }] }],
    },
  },
  {
    files: ['src/core/**/*.{js,jsx}'],
    rules: {
      'no-restricted-imports': ['error', { patterns: [{ group: ['@/features/*', '@/app/*'], message: 'core must not depend on features or the app shell' }] }],
    },
  },
  {
    files: ['src/shared/**/*.{js,jsx}'],
    rules: {
      'no-restricted-imports': ['error', { patterns: [{ group: ['@/features/*', '@/app/*', '@/core/*'], message: 'shared is presentational only' }] }],
    },
  },
  {
    files: ['**/*.test.{js,jsx}', 'src/test/**'],
    languageOptions: { globals: { ...globals.browser, ...globals.vitest } },
    rules: { 'react-refresh/only-export-components': 'off' },
  },
]);
