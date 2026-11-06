import { expect, test } from '@playwright/test';

test('http mode with an unreachable API shows clear errors, not a blank page', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('SYNTHETIC DATA')).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: 'Backend unreachable' })).toBeVisible();
  await expect(page.getByRole('alert').filter({ hasText: 'Backend unreachable.' }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Retry' }).first()).toBeVisible();
  // other routes degrade the same way
  await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name: 'Approvals' }).click();
  await expect(page.getByRole('alert').first()).toBeVisible();
  await page.screenshot({ path: 'screenshots/http-backend-down.jpg', type: 'jpeg', quality: 55, fullPage: true });
});
