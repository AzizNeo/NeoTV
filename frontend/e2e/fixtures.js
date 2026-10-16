/**
 * Shared fixtures. `page` is wrapped so that EVERY test also asserts:
 *  - no Content-Security-Policy violation happened (the production policy is served by preview);
 *  - no uncaught exception was thrown in the page.
 * A feature that works but needs the policy loosened — or throws in the background — fails here.
 */
import { test as base, expect } from '@playwright/test';

export const ADMIN = { username: 'e2e-admin', password: process.env.E2E_ADMIN_PASSWORD ?? 'Playwright-Only-Secret-2026!' };
export const offline = Boolean(process.env.E2E_OFFLINE);

export const test = base.extend({
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

/**
 * Leaves the player the way a viewer does (navigating away unmounts it, which releases the
 * session with sendBeacon) and waits until the server agrees: the admin "Sessions" page shows no
 * open stream. Plans allow a limited number of simultaneous streams, so a test that leaves a
 * session open would make the next playback test hit STREAM_LIMIT_EXCEEDED. (Beacons are not
 * reliably visible to Playwright, so we check the server's state, not the request.)
 */
export async function leavePlayer(page) {
  await page.goto('/admin/sessions');
  await expect(async () => {
    await page.reload();
    await expect(page.getByText('Açık yayın oturumu yok')).toBeVisible({ timeout: 2_000 });
  }).toPass({ timeout: 20_000 });
}

/** The player's error card (instead of a video): its message, or null while there is none. */
export async function playerProblem(page) {
  const card = page.getByRole('dialog').locator('h2 + p');
  return (await card.count()) ? card.first().textContent() : null;
}
