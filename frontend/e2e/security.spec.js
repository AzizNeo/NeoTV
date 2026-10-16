import { expect, test } from './fixtures';

const directives = (header) => Object.fromEntries(header.split(';').map((d) => d.trim().split(/\s+/)).filter((d) => d[0]).map(([k, ...v]) => [k, v]));

test('the app is served under the production CSP', async ({ request }) => {
  const response = await request.get('/login');
  const csp = directives(response.headers()['content-security-policy'] ?? '');
  expect(csp['script-src']).toEqual(["'self'"]);
  expect(csp['object-src']).toEqual(["'none'"]);
  expect(csp['frame-ancestors']).toEqual(["'none'"]);
  expect(response.headers()['x-content-type-options']).toBe('nosniff');
});

test('API responses forbid everything a document could do', async ({ request }) => {
  const response = await request.get('/api/v1/health/live');
  expect(directives(response.headers()['content-security-policy'] ?? '')['default-src']).toEqual(["'none'"]);
});

test.describe('provoking the policy on purpose', () => {
  test.use({ allowCspViolations: true });

  test('injected inline script is blocked — and reported', async ({ page, cspViolations }) => {
    await page.goto('/login');
    const ran = await page.evaluate(async () => {
      window.__injected = false;
      const s = document.createElement('script');
      s.textContent = 'window.__injected = true';
      document.body.append(s);
      await new Promise((r) => setTimeout(r, 200));
      return window.__injected;
    });
    expect(ran).toBe(false);
    await expect.poll(() => cspViolations.some((v) => v.startsWith('script-src'))).toBe(true);
  });
});
