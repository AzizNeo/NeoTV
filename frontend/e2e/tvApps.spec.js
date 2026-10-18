import { expect, signIn, test } from './fixtures';

/**
 * End to end as a TV app would use NeoTV (ADR-0011): the owner creates sign-in details on the TV
 * apps page, then an Xtream client logs in, lists live channels and opens one — through the
 * production build, under the production CSP. (nginx maps <server>/player_api.php onto this path.)
 */
const XTREAM = '/api/v1/xtream';

test('a TV app signs in with details from the TV apps page and opens a channel', async ({ page, viewer, request }) => {
  await signIn(page, viewer);
  await page.goto('/tv-apps');
  await page.getByRole('button', { name: 'TV uygulaması ekle' }).click();
  const form = page.getByRole('dialog');
  await form.getByLabel('Cihaz adı').fill('Salon TV');
  await form.getByRole('button', { name: 'Oluştur' }).click();

  const shown = page.getByRole('dialog', { name: 'Giriş bilgileri hazır' });
  await expect(shown.getByRole('alert')).toContainText('yalnızca şimdi');
  const values = await shown.locator('dd code').allTextContents();
  const [, username, password] = values; // server, username, password, M3U, EPG
  expect(username).toMatch(/^[a-z2-9]{10}$/);
  expect(password).toMatch(/^[a-z2-9]{12}$/);
  await shown.getByRole('button', { name: 'Tamam, kaydettim' }).click();
  await expect(page.getByText(password)).toHaveCount(0); // shown once, then gone
  await expect(page.getByRole('listitem').filter({ hasText: 'Salon TV' })).toBeVisible();

  // ── now the app ──
  const auth = { username, password };
  const login = await (await request.get(`${XTREAM}/player_api.php`, { params: auth })).json();
  expect(login.user_info).toMatchObject({ auth: 1, status: 'Active', username });
  const streams = await (await request.get(`${XTREAM}/player_api.php`, { params: { ...auth, action: 'get_live_streams' } })).json();
  expect(streams.length).toBeGreaterThan(0);
  const opened = await request.get(`${XTREAM}/live/${username}/${password}/${streams[0].stream_id}.m3u8`, { maxRedirects: 0 });
  expect(opened.status()).toBe(302);
  expect(opened.headers().location).toContain('/api/v1/playback/proxy?');
  const wrong = await request.get(`${XTREAM}/player_api.php`, { params: { username, password: 'x'.repeat(12) } });
  expect(await wrong.json()).toEqual({ user_info: { auth: 0 } });
});
