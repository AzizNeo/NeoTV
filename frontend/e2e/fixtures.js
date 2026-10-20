/**
 * Shared fixtures. `page` is wrapped so that EVERY test also asserts:
 *  - no Content-Security-Policy violation happened (the production policy is served by preview);
 *  - no uncaught exception was thrown in the page.
 * A feature that works but needs the policy loosened — or throws in the background — fails here.
 *
 * Isolation: a test that changes per-account state (stream slots, language preference, sign-out)
 * uses `viewer` — a fresh account registered through the public API for that test alone. Only
 * read-only admin checks share the seeded `ADMIN`. No test waits for another one to clean up.
 */
import { randomBytes } from 'node:crypto';
import { test as base, expect } from '@playwright/test';

export const ADMIN = { username: 'e2e-admin', password: process.env.E2E_ADMIN_PASSWORD ?? 'Playwright-Only-Secret-2026!' };
export const offline = Boolean(process.env.E2E_OFFLINE);

export const test = base.extend({
  /** A fresh account of this test only (registered like a real visitor; nothing shared). */
  viewer: async ({ request }, use, testInfo) => {
    const username = `e2e-${testInfo.testId.slice(0, 8)}-${randomBytes(3).toString('hex')}`;
    const password = `Pw-${randomBytes(9).toString('base64url')}-7q!`;
    const response = await request.post('/api/v1/auth/register', { data: { username, password } });
    expect(response.status(), `register ${username}: ${await response.text()}`).toBe(201);
    await use({ username, password });
  },
  /** Opt-out for tests that provoke a violation on purpose (they assert on `cspViolations`). */
  allowCspViolations: [false, { option: true }],
  cspViolations: async ({}, use) => use([]), // eslint-disable-line no-empty-pattern -- Playwright's fixture signature
  /** Opt-out for tests that throw on purpose (they assert on `pageErrors`). */
  allowPageErrors: [false, { option: true }],
  pageErrors: async ({}, use) => use([]), // eslint-disable-line no-empty-pattern -- Playwright's fixture signature
  page: async ({ page, allowCspViolations, cspViolations: violations, allowPageErrors, pageErrors: errors }, use, testInfo) => {
    // One address per test, like separate visitors: the API's per-address limits (refresh, telemetry,
    // sign-in) then apply to this test alone instead of the whole suite (tools/e2e_server.py trusts
    // one proxy hop). Browser traffic only: setup calls and metric reads stay 127.0.0.1.
    await page.context().setExtraHTTPHeaders({ 'X-Forwarded-For': visitorAddress(testInfo.testId) });
    // Reported straight to the test process, so nothing is lost when the page navigates.
    await page.exposeFunction('__e2eCspViolation', (text) => violations.push(text));
    await page.addInitScript(() => {
      document.addEventListener('securitypolicyviolation', (e) => {
        window.__e2eCspViolation(`${e.effectiveDirective} blocked ${e.blockedURI || 'inline'} (${e.sourceFile}:${e.lineNumber})`);
      });
    });
    page.on('pageerror', (error) => errors.push(`uncaught: ${error.message}`));
    // Failed API calls, for showReady()'s report (path only: query strings can hold grants).
    const failures = [];
    page.on('response', (response) => {
      const url = new URL(response.url());
      if (url.pathname.startsWith('/api/') && response.status() >= 400) {
        failures.push(`${response.request().method()} ${url.pathname} → ${response.status()}`);
      }
    });
    page.apiFailures = failures;
    await use(page);
    if (!allowCspViolations) expect(violations, 'CSP violations').toEqual([]);
    if (!allowPageErrors) expect(errors, 'uncaught page errors').toEqual([]);
  },
});

export { expect };

/** A stable private address per test id (10.x.y.z): retries of a test are the same visitor. */
export function visitorAddress(testId) {
  let hash = 0;
  for (const char of testId) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return `10.${(hash >>> 16) & 255}.${(hash >>> 8) & 255}.${(hash & 255) || 1}`;
}

/** Signs in through the real form; lands past the profile picker. */
export async function signIn(page, { username = ADMIN.username, password = ADMIN.password } = {}) {
  await page.goto('/login');
  await page.locator('#login-username').fill(username);
  await page.locator('#login-password').fill(password);
  await page.locator('button[type=submit]').click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'));
  if (new URL(page.url()).pathname.startsWith('/profiles')) {
    await page.locator('main button').first().click();
    await page.waitForURL((url) => !url.pathname.startsWith('/profiles'));
  }
}

/**
 * Waits for `locator` to be visible; if it never is, fails with what the page shows instead —
 * its URL, the start of its visible text and the API calls that failed — so an intermittent
 * failure in CI explains itself without the trace.
 */
export async function showReady(page, locator, what, timeout = 20_000) {
  try {
    await locator.waitFor({ state: 'visible', timeout });
  } catch (error) {
    const text = (await page.locator('body').innerText().catch(() => '')).replace(/\s+/g, ' ').slice(0, 300);
    const failed = (page.apiFailures ?? []).slice(-8).join('; ') || 'none';
    throw new Error(`${what} never appeared.\n  URL: ${page.url()}\n  Page shows: ${text}\n  Failed API calls: ${failed}`, { cause: error });
  }
  return locator;
}

/** The player's error card (instead of a video): its message, or null while there is none. */
export async function playerProblem(page) {
  const card = page.getByRole('dialog').locator('h2 + p');
  return (await card.count()) ? card.first().textContent() : null;
}
