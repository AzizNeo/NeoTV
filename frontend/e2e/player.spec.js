import { expect, leavePlayer, offline, playerProblem, signIn, test } from './fixtures';

// Hosts of the seeded demo sources: with proxy delivery the browser must never contact them.
const ORIGINS = ['test-streams.mux.dev', 'cloudfront.net', 'unified-streaming.com', 'devstreaming-cdn.apple.com'];

test('proxy delivery: the stream URL of the origin never reaches the browser', async ({ page }) => {
  await signIn(page);
  const requests = [];
  page.on('request', (request) => requests.push(request.url()));
  await page.goto('/title/big-buck-bunny');
  await page.locator('main').getByRole('button', { name: 'Oynat' }).click();
  await expect.poll(() => requests.some((url) => url.includes('/api/v1/playback/proxy')), { timeout: 15_000 }).toBe(true);
  expect(requests.filter((url) => ORIGINS.some((host) => url.includes(host)))).toEqual([]);
  await leavePlayer(page);
});

test('a video actually plays (hls.js in its blob worker, under the CSP)', async ({ page }) => {
  test.skip(offline, 'needs the internet: the demo streams are public test streams');
  test.slow();
  await signIn(page);
  await page.goto('/title/big-buck-bunny');
  await page.locator('main').getByRole('button', { name: 'Oynat' }).click();
  const video = page.locator('video');
  // Either the video or the player's error card — and if it is the card, say what it says.
  await expect(video.or(page.getByRole('dialog').locator('h2 + p'))).toBeAttached({ timeout: 30_000 });
  expect(await playerProblem(page), 'the player showed an error card').toBeNull();
  // The error card can also come later (after retries): the poll then reports its text as the value.
  const readyOrProblem = async () => (await playerProblem(page)) ?? video.evaluate((v) => v.readyState);
  await expect.poll(readyOrProblem, { timeout: 30_000, message: 'video ready (HAVE_FUTURE_DATA) — a text is the error card' }).toBeGreaterThanOrEqual(3);
  const start = await video.evaluate((v) => v.currentTime);
  await expect.poll(() => video.evaluate((v) => v.currentTime), { timeout: 15_000 }).toBeGreaterThan(start + 1);
  await leavePlayer(page);
});
