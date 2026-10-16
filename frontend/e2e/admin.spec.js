import { expect, signIn, test } from './fixtures';

test.beforeEach(async ({ page }) => signIn(page));

const tabs = (page) => page.getByRole('navigation', { name: 'Yönetim bölümleri' });

test('tabs navigate between sections without nesting the URL', async ({ page }) => {
  // Regression: relative links inside the /admin/* splat route led to /admin/overview/catalog/…
  await page.goto('/admin');
  await expect(page).toHaveURL(/\/admin\/overview$/);
  await tabs(page).getByRole('link', { name: 'Katalog' }).click();
  await expect(page).toHaveURL(/\/admin\/catalog$/);
  await expect(page.getByText('Sintel').first()).toBeVisible();
  await tabs(page).getByRole('link', { name: 'Kullanıcılar' }).click();
  await expect(page).toHaveURL(/\/admin\/users$/);
  await expect(page.getByText('e2e-admin').first()).toBeVisible();
  await tabs(page).getByRole('link', { name: 'TMDB' }).click();
  await expect(page).toHaveURL(/\/admin\/tmdb$/);
});

test('an unknown admin address falls back to the overview', async ({ page }) => {
  await page.goto('/admin/no-such-section');
  await expect(page).toHaveURL(/\/admin\/overview$/);
});

test('TMDB without a token explains the setup instead of failing', async ({ page }) => {
  await page.goto('/admin/tmdb');
  await expect(page.getByText('TMDB yapılandırılmamış')).toBeVisible();
  await expect(page.getByRole('search')).toHaveCount(0);
});
