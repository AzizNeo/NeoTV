import { expect, playerProblem, showReady, signIn, test } from './fixtures';

/**
 * Catch-up TV end to end (ADR-0012), on the synthetic archive tools/e2e_server.py seeds for
 * "Akamai Live" (placeholder segments: the path is tested, not the picture).
 */
const watchAgain = (page) => page.getByRole('button', { name: /, tekrar izle \(Akamai Live\)$/ }).first();

async function familyPlan(request, { username, password }) {
  const login = await (await request.post('/api/v1/auth/login', { data: { username, password } })).json();
  const trial = await request.post('/api/v1/billing/trial', { headers: { Authorization: `Bearer ${login.data.access_token}` } });
  expect(trial.status()).toBe(200); // trial = Family: 7 days of catch-up
}

test('a past programme plays from the archive through a signed window', async ({ page, viewer, request }) => {
  await familyPlan(request, viewer);
  await signIn(page, viewer);
  await page.goto('/live');
  const opened = page.waitForRequest((r) => r.url().endsWith('/api/v1/playback/sessions') && r.method() === 'POST');
  const playlist = page.waitForResponse((r) => /\/api\/v1\/live\/archive\/\d+\/\d+-\d+\/index\.m3u8\?/.test(r.url()));
  await (await showReady(page, watchAgain(page), 'A "watch again" programme in the guide')).click();

  const body = (await opened).postDataJSON();
  expect(body.window.start < body.window.end).toBe(true);
  const response = await playlist;
  expect(response.status()).toBe(200);
  const text = await response.text();
  expect(text).toContain('#EXT-X-PLAYLIST-TYPE:VOD');
  expect(text).toContain('#EXT-X-ENDLIST');
  expect(text.split('\n').filter((line) => line.endsWith('.ts') || line.includes('.ts?')).length).toBeGreaterThan(0);
  expect(response.url()).not.toContain('akamaized.net'); // the origin never reaches the browser
});

test('without catch-up in the plan, the player says so', async ({ page, viewer }) => {
  await signIn(page, viewer); // free plan
  await page.goto('/live');
  await (await showReady(page, watchAgain(page), 'A "watch again" programme in the guide')).click();
  await expect.poll(() => playerProblem(page), { timeout: 15_000 }).toContain('Geriye dönük izleme planınızda yok');
});
