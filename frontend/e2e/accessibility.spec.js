import AxeBuilder from '@axe-core/playwright';
import { test, expect, signIn } from './fixtures';

/**
 * WCAG 2.2 AA, automatically, in both themes: every listed page must have zero axe violations.
 * Colour contrast is the usual regression (a new token, a brand colour used as text), and it differs
 * per theme — so each page is checked in light and in dark. Automated checks find a large share of
 * issues, not all; they keep fixed problems fixed.
 */
const WCAG = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'];
const PUBLIC = ['/login', '/register', '/forgot-password'];
const VIEWER = ['/', '/browse', '/title/sintel', '/live', '/plans', '/favorites', '/history', '/account', '/devices', '/profiles'];

async function expectNoViolations(page, path) {
  await page.goto(path);
  await page.waitForLoadState('networkidle');
  await expect(page.locator('main')).toBeVisible();
  const { violations } = await new AxeBuilder({ page }).withTags(WCAG).analyze();
  const report = violations.map((v) => `${v.id} (${v.impact}) ×${v.nodes.length}: ${v.help} — ${v.nodes[0].target.join(' ')}`);
  expect.soft(report, `axe on ${path}`).toEqual([]); // soft: one run reports every page
}

for (const colorScheme of ['light', 'dark']) {
  test.describe(`accessibility, ${colorScheme} theme`, () => {
    test.use({ colorScheme });

    test('public pages', async ({ page }) => {
      for (const path of PUBLIC) await expectNoViolations(page, path);
    });

    test('viewer pages', async ({ page, viewer }) => {
      await signIn(page, viewer);
      for (const path of VIEWER) await expectNoViolations(page, path);
    });

    test('admin', async ({ page }) => {
      await signIn(page);
      await expectNoViolations(page, '/admin');
    });
  });
}
