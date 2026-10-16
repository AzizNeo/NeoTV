/**
 * End-to-end browser tests: the production build (`vite preview`, which serves the production
 * security headers — CSP included) against a fresh, seeded backend (python -m tools.e2e_server).
 *
 *   npm run build && npm run e2e          # E2E_OFFLINE=1 skips tests that need the internet
 *
 * Every test fails on a CSP violation or an uncaught page error (see e2e/fixtures.js).
 */
import { defineConfig, devices } from '@playwright/test';

const CI = Boolean(process.env.CI);
const python = process.env.E2E_PYTHON ?? (process.platform === 'win32' ? '..\\.venv\\Scripts\\python.exe' : 'python');

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1, // one shared backend; tests sign in independently but share its data
  retries: CI ? 1 : 0,
  forbidOnly: CI,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: CI ? [['github'], ['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: 'http://127.0.0.1:4173',
    locale: 'tr-TR',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    launchOptions: process.env.PW_CHROMIUM_PATH ? { executablePath: process.env.PW_CHROMIUM_PATH } : {},
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      command: `${python} -m tools.e2e_server`,
      cwd: '..',
      url: 'http://127.0.0.1:5000/api/v1/health/ready',
      timeout: 180_000,
      reuseExistingServer: false,
      stdout: 'pipe',
    },
    {
      command: 'npx vite preview --host 127.0.0.1 --port 4173 --strictPort',
      url: 'http://127.0.0.1:4173/login',
      timeout: 60_000,
      reuseExistingServer: false,
    },
  ],
});
