/**
 * Captures the README screenshots from a running NeoTV (seeded with `python -m tools.seed_demo`).
 *
 *   npm i --no-save playwright@1 && npx playwright install chromium
 *   NEOTV_USER=admin NEOTV_PASSWORD=… node scripts/screenshots.mjs [baseUrl=http://127.0.0.1:5173]
 *
 * Output: ../docs/screenshots/*.png (1440×900, plus one 390×844 mobile view).
 * Playwright is deliberately not a dependency: only maintainers refreshing the README need it.
 */
/* eslint-disable no-console -- maintainer CLI: progress on stdout is its interface */
import { mkdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const base = (process.argv[2] ?? 'http://127.0.0.1:5173').replace(/\/$/, '');
const user = process.env.NEOTV_USER;
const password = process.env.NEOTV_PASSWORD;
if (!user || !password) throw new Error('Set NEOTV_USER and NEOTV_PASSWORD');

const out = resolve(dirname(fileURLToPath(import.meta.url)), '../../docs/screenshots');
await mkdir(out, { recursive: true });

const SHOTS = [
  { name: 'home', path: '/' },
  { name: 'live-tv', path: '/live' },
  { name: 'admin', path: '/admin/overview' },
  { name: 'plans', path: '/plans' },
];

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark' });
  const page = await context.newPage();

  await page.goto(`${base}/login`);
  await page.waitForSelector('#login-username'); // SPA: the form renders after the bundle boots
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: `${out}/login.png` });
  console.log('✔ login');
  await page.fill('#login-username', user);
  await page.fill('#login-password', password);
  await page.click('button[type=submit]');
  await page.waitForURL((url) => !url.pathname.startsWith('/login'));
  if (new URL(page.url()).pathname.startsWith('/profiles')) {
    await page.locator('main button').first().click(); // "who is watching?" → first profile
    await page.waitForURL((url) => !url.pathname.startsWith('/profiles'));
  }

  for (const shot of SHOTS) {
    await page.goto(`${base}${shot.path}`);
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(600); // lazy rows / images settle
    await page.screenshot({ path: `${out}/${shot.name}.png` });
    console.log(`✔ ${shot.name}`);
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${base}/`);
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${out}/home-mobile.png` });
  console.log('✔ home-mobile');
} finally {
  await browser.close();
}
