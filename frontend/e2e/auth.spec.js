import { ADMIN, expect, signIn, test } from './fixtures';

test('a wrong password is refused with a clear message', async ({ page }) => {
  await page.goto('/login');
  await page.locator('#login-username').fill(ADMIN.username);
  await page.locator('#login-password').fill(`${ADMIN.password}-wrong`);
  await page.locator('button[type=submit]').click();
  await expect(page.getByText('Kullanıcı adı veya şifre hatalı.')).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
});

test('signed-out visitors are sent to the login page', async ({ page }) => {
  await page.goto('/browse');
  await expect(page).toHaveURL(/\/login/);
});

test('sign in, then sign out from the account menu', async ({ page }) => {
  await signIn(page);
  await expect(page.getByRole('navigation').first()).toBeVisible();
  await page.getByRole('button', { name: 'Hesap menüsü' }).click();
  await page.getByRole('button', { name: /Çıkış yap/ }).click();
  await expect(page).toHaveURL(/\/login/);
});
