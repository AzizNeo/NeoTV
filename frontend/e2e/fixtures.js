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
  page: async ({ page, allowCspViolations, cspViolations: violations }, use) => {
    const errors = [];
    // Reported straight to the test process, so nothing is lost when the page navigates.
    await page.exposeFunction('__e2eCspViolation', (text) => violations.push(text));
    await page.addInitScript(() => {
      document.addEventListener('securitypolicyviolation', (e) => {
        window.__e2eCspViolation(`${e.effectiveDirective} blocked ${e.blockedURI || 'inline'} (${e.sourceFile}:${e.lineNumber})`);
      });
    });
    page.on('pageerror', (error) => errors.push(`uncaught: ${error.message}`));
    await use(page);
    if (!allowCspViolations) expect(violations, 'CSP violations').toEqual([]);
    expect(errors, 'uncaught page errors').toEqual([]);
  },
});

export { expect };

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

/** The player's error card (instead of a video): its message, or null while there is none. */
export async function playerProblem(page) {
  const card = page.getByRole('dialog').locator('h2 + p');
  return (await card.count()) ? card.first().textContent() : null;
}
