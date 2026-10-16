import { expect, signIn, test } from './fixtures';

test.beforeEach(async ({ page }) => signIn(page));

test('home shows the seeded titles', async ({ page }) => {
  await expect(page.getByText('Sintel').first()).toBeVisible();
  await expect(page.getByText('Big Buck Bunny').first()).toBeVisible();
});

test('browse finds a title by name', async ({ page }) => {
  await page.goto('/browse');
  await page.getByRole('searchbox').first().fill('sintel');
  await expect(page.getByRole('link', { name: /Sintel/ }).first()).toBeVisible();
});

test('a title page offers playback', async ({ page }) => {
  await page.goto('/title/sintel');
  await expect(page.getByRole('heading', { name: 'Sintel' })).toBeVisible();
  await expect(page.locator('main').getByRole('button', { name: 'Oynat' })).toBeVisible();
});

test('live TV lists the channels', async ({ page }) => {
  await page.goto('/live');
  await expect(page.getByText('Akamai Live').first()).toBeVisible();
});

test('switching to English changes the interface and the content', async ({ page }) => {
  await page.getByRole('button', { name: 'Hesap menüsü' }).click();
  await page.getByRole('group', { name: 'Dil' }).getByText('English').click(); // the radio is visually hidden; users click its label
  await expect(page.getByRole('group', { name: 'Language' }).getByRole('radio', { name: 'English' })).toBeChecked();
  await page.goto('/title/sintel');
  await expect(page.locator('main').getByRole('button', { name: 'Play' })).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('lang', 'en');
});
