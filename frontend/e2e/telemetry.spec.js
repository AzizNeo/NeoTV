import { expect, signIn, test } from './fixtures';

// The server's truth, read where Prometheus reads it (the backend answers its metrics to localhost).
// Beacons are not reliably observable from Playwright; the counters they move are.
const METRICS = 'http://127.0.0.1:5000/api/v1/kernel/metrics';

async function metric(request, sample) {
  const text = await (await request.get(METRICS)).text();
  const line = text.split('\n').find((l) => l.startsWith(`${sample} `));
  return line ? Number(line.split(' ')[1]) : 0;
}

/** Leaving the page hides it: that is when the SPA sends its queued telemetry. */
const leave = (page) => page.goto('/login');

test('Web Vitals measured in the browser reach the server', async ({ page, request, viewer }) => {
  const before = await metric(request, 'neotv_web_vital_seconds_count{name="TTFB"}');
  await signIn(page, viewer);
  await page.goto('/browse');
  await expect(page.getByRole('searchbox').first()).toBeVisible();
  await leave(page);
  await expect.poll(() => metric(request, 'neotv_web_vital_seconds_count{name="TTFB"}'), { timeout: 15_000 }).toBeGreaterThan(before);
});

test.describe('errors thrown on purpose', () => {
  test.use({ allowPageErrors: true });

  test('an uncaught error in the page is reported once, under the production CSP', async ({ page, request, viewer, pageErrors }) => {
    const sample = 'neotv_client_errors_total{source="error"}';
    const before = await metric(request, sample);
    await signIn(page, viewer);
    await page.evaluate(() => {
      for (let i = 0; i < 5; i += 1) setTimeout(() => { throw new Error('e2e telemetry probe'); });
    });
    await expect.poll(() => pageErrors.length).toBe(5); // the browser really threw, five times…
    await leave(page);
    await expect.poll(() => metric(request, sample), { timeout: 15_000 }).toBe(before + 1); // …reported once
  });
});
