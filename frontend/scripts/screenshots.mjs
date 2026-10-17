/**
 * Captures the README screenshots and the demo GIF from a running NeoTV seeded with
 * `python -m tools.seed_demo` (sources must be playable from the machine running this).
 *
 *   npm i --no-save playwright@1 && npx playwright install chromium
 *   NEOTV_USER=admin NEOTV_PASSWORD=… node scripts/screenshots.mjs [baseUrl=http://127.0.0.1:5173]
 *
 * Output (../docs/screenshots/): 1440×900 PNGs, one 390×844 mobile view, and demo.gif — a short
 * walk-through recorded with Chromium's screencast (needs ffmpeg on PATH to assemble the GIF).
 * Optional: CHROMIUM_PATH (a system Chromium), NEOTV_SKIP_GIF=1, NEOTV_SKIP_PLAYBACK=1 (no stream needed:
 * keeps player.png, up-next.png and demo.gif, refreshes every page screenshot).
 * Playwright is deliberately not a dependency: only maintainers refreshing the README need it.
 */
/* eslint-disable no-console -- maintainer CLI: progress on stdout is its interface */
import { execFileSync } from 'node:child_process';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const base = (process.argv[2] ?? 'http://127.0.0.1:5173').replace(/\/$/, '');
const user = process.env.NEOTV_USER;
const password = process.env.NEOTV_PASSWORD;
if (!user || !password) throw new Error('Set NEOTV_USER and NEOTV_PASSWORD');

const out = resolve(dirname(fileURLToPath(import.meta.url)), '../../docs/screenshots');
await mkdir(out, { recursive: true });
const DESKTOP = { width: 1440, height: 900 };
const SKIP_PLAYBACK = Boolean(process.env.NEOTV_SKIP_PLAYBACK);

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});

/** A signed-in page in the given language and theme (both are per-device choices in localStorage). */
async function session({ locale = 'tr', theme = 'dark', viewport = DESKTOP } = {}) {
  const context = await browser.newContext({ viewport, colorScheme: theme });
  await context.addInitScript(
    ([l, t]) => {
      if (!sessionStorage.getItem('shots-init')) {
        localStorage.setItem('neotv.locale', l);
        localStorage.setItem('neotv.theme', t);
        sessionStorage.setItem('shots-init', '1');
      }
    },
    [locale, theme],
  );
  const page = await context.newPage();
  await page.goto(`${base}/login`);
  await page.waitForSelector('#login-username'); // SPA: the form renders after the bundle boots
  await page.waitForLoadState('networkidle');
  return { context, page };
}

async function signIn(page) {
  await page.fill('#login-username', user);
  await page.fill('#login-password', password);
  await page.click('button[type=submit]');
  await page.waitForURL((url) => !url.pathname.startsWith('/login'));
  if (new URL(page.url()).pathname.startsWith('/profiles')) {
    await page.locator('main button').first().click(); // "who is watching?" → first profile
    await page.waitForURL((url) => !url.pathname.startsWith('/profiles'));
  }
}

async function visit(page, path) {
  await page.goto(`${base}${path}`);
  await page.waitForLoadState('networkidle');
  await page.waitForTimeout(700); // lazy rows / images settle
}

async function shot(page, name) {
  await page.screenshot({ path: `${out}/${name}.png` });
  console.log(`✔ ${name}`);
}

/** Start the first playable title on a detail page and wait until frames are on screen. */
async function play(page, slug) {
  await visit(page, `/title/${slug}`);
  await page.locator('main').getByRole('button').first().click();
  await page.waitForFunction(() => document.querySelector('video')?.readyState >= 3, null, { timeout: 30_000 });
}

const seek = (page, seconds) => page.evaluate((s) => (document.querySelector('video').currentTime = s), seconds);
const wake = (page) => page.mouse.move(700 + Math.random() * 20, 380); // controls appear on movement

try {
  // ── Signed out ───────────────────────────────────────────────────────
  {
    const { context, page } = await session();
    await shot(page, 'login');

    // ── Player first: the home page then shows "continue watching" ────
    await signIn(page);
    if (!SKIP_PLAYBACK) {
      await play(page, 'sintel');
      await seek(page, 9);
      await wake(page);
      await page.getByRole('button', { name: 'Ayarlar' }).click();
      await page.getByRole('menuitem', { name: /Altyazı/ }).click();
      await page.getByRole('menuitemradio', { name: 'Türkçe' }).click();
      await page.waitForTimeout(1500);
      await wake(page);
      await page.getByRole('button', { name: 'Ayarlar' }).click();
      await page.waitForTimeout(300);
      await shot(page, 'player');
      await page.keyboard.press('Escape');
      await page.keyboard.press('Escape');

      await play(page, 'test-streams');
      const duration = await page.evaluate(() => document.querySelector('video').duration);
      await seek(page, duration - 14);
      await page.waitForSelector('section[aria-label="Sonraki bölüm"]', { timeout: 10_000 });
      await wake(page);
      await page.waitForTimeout(500);
      await shot(page, 'up-next');
      await page.keyboard.press('Escape');
    }

    for (const [name, path] of [
      ['home', '/'],
      ['browse', '/browse'],
      ['title', '/title/test-streams'],
      ['live-tv', '/live'],
      ['plans', '/plans'],
      ['admin', '/admin/overview'],
    ]) {
      await visit(page, path);
      await shot(page, name);
    }
    await context.close();
  }

  // ── The same app in light theme and in English ─────────────────────
  {
    const { context, page } = await session({ theme: 'light' });
    await signIn(page);
    await visit(page, '/');
    await shot(page, 'home-light');
    await context.close();
  }
  {
    const { context, page } = await session({ locale: 'en' });
    await signIn(page);
    await visit(page, '/title/sintel');
    await shot(page, 'title-en');
    await context.close();
  }
  {
    const { context, page } = await session({ viewport: { width: 390, height: 844 } });
    await signIn(page);
    await visit(page, '/');
    await shot(page, 'home-mobile');
    await context.close();
  }

  // ── demo.gif: a ~20-second walk-through ────────────────────────────
  if (!process.env.NEOTV_SKIP_GIF && !SKIP_PLAYBACK) {
    const frames = join(out, '.frames');
    await rm(frames, { recursive: true, force: true });
    await mkdir(frames);
    const { context, page } = await session({ viewport: { width: 1280, height: 720 } });
    await signIn(page);
    await visit(page, '/');

    // Chromium screencast: a frame whenever the page repaints, with its timestamp.
    const captured = [];
    const cdp = await context.newCDPSession(page);
    cdp.on('Page.screencastFrame', ({ data, metadata, sessionId }) => {
      captured.push({ data, at: metadata.timestamp });
      cdp.send('Page.screencastFrameAck', { sessionId }).catch(() => {});
    });
    await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 90, maxWidth: 1280, maxHeight: 720 });

    await page.waitForTimeout(1500);
    await page.mouse.wheel(0, 500);
    await page.waitForTimeout(1200);
    await page.mouse.wheel(0, -500);
    await page.waitForTimeout(600);
    await page.getByRole('link', { name: /Ayrıntılar/ }).first().click();
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1500);
    await page.locator('main').getByRole('button').first().click();
    await page.waitForFunction(() => document.querySelector('video')?.readyState >= 3, null, { timeout: 30_000 });
    await seek(page, 9);
    await page.waitForTimeout(1500);
    await wake(page);
    await page.getByRole('button', { name: 'Ayarlar' }).click();
    await page.waitForTimeout(800);
    await page.getByRole('menuitem', { name: /Altyazı/ }).click();
    await page.waitForTimeout(800);
    await page.getByRole('menuitemradio', { name: 'Türkçe' }).click();
    await page.waitForTimeout(2500);
    await page.keyboard.press('Shift+Slash');
    await page.waitForTimeout(2200);
    await page.keyboard.press('Escape');
    await page.waitForTimeout(1000);
    await cdp.send('Page.stopScreencast');
    await context.close();

    // Frames → concat list with each frame's real on-screen time → palette GIF (10 fps, 800 px).
    const list = [];
    for (const [i, frame] of captured.entries()) {
      const file = join(frames, `${String(i).padStart(5, '0')}.jpg`);
      await writeFile(file, Buffer.from(frame.data, 'base64'));
      const next = captured[i + 1]?.at ?? frame.at + 1;
      list.push(`file '${file}'`, `duration ${Math.max(0.01, next - frame.at).toFixed(3)}`);
    }
    list.push(`file '${join(frames, `${String(captured.length - 1).padStart(5, '0')}.jpg`)}'`); // concat demuxer: repeat the last
    await writeFile(join(frames, 'list.txt'), list.join('\n'));
    const filters = 'fps=10,scale=800:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle';
    try {
      execFileSync('ffmpeg', ['-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', join(frames, 'list.txt'), '-vf', filters, `${out}/demo.gif`]);
      console.log(`✔ demo.gif (${captured.length} frames)`);
    } catch (error) {
      console.log(`✘ demo.gif: ffmpeg failed or is missing (${error.message.split('\n')[0]})`);
    }
    await rm(frames, { recursive: true, force: true });
  }
} finally {
  await browser.close();
}
