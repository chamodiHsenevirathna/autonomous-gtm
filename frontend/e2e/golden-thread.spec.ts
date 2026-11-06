import { expect, test } from '@playwright/test';
import { approveFromQueue, nav, submitEnquiry } from './helpers';

test('golden thread through the UI', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });

  await page.goto('/');
  await expect(page.getByText('SYNTHETIC DATA')).toBeVisible();
  await expect(page.getByText('SIMULATED MODEL')).toBeVisible();
  await expect(page.locator('.clock time')).toContainText('09 Mar 2026');

  // 1. submit the enquiry
  await submitEnquiry(page);

  // 2. lead + account with provenance
  await nav(page, 'Leads');
  await expect(page.getByRole('cell', { name: /Priya Raman/ })).toBeVisible();
  await nav(page, 'Accounts');
  await page.getByRole('link', { name: 'Harbourline Freight Group' }).click();
  await expect(page.getByRole('heading', { name: 'Harbourline Freight Group', level: 1 })).toBeVisible();
  await expect(page.locator('details.conflict summary')).toContainText('conflict');
  await expect(page.locator('.chip', { hasText: 'orgdata (simulated)' }).first()).toBeVisible();
  await expect(page.getByText('AI-written').first()).toBeVisible();
  await expect(page.getByText('human-owned').first()).toBeVisible();

  // 3. approve the CRM proposal
  await nav(page, 'Approvals');
  await page.getByRole('link', { name: /^#301 / }).click();
  await expect(page.getByText('Exact payload to be executed')).toBeVisible();
  await expect(page.locator('.hash-full code')).toHaveText(/^[0-9a-f]{64}$/);
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Gateway and execution outcome' })).toBeVisible();
  await expect(page.locator('.checks li')).toHaveCount(13);
  await expect(page.locator('.chk-failed')).toHaveCount(0);

  // 4. dependent reply unblocks; first see it is decidable
  await page.getByRole('link', { name: /^#302 / }).click();
  await expect(page.getByRole('heading', { name: 'Your decision' })).toBeVisible();

  // 5. edit with a price -> blocked, with diff
  await page.getByLabel('Edit and approve').check();
  const body = page.getByLabel('Body');
  const original = await body.inputValue();
  await body.fill(original + '\nOur fee would be EUR 20,000 fixed.');
  await page.getByRole('button', { name: 'Edit and approve', exact: true }).click();
  await expect(page.getByText('Execution was blocked at the gateway.')).toBeVisible();
  await expect(page.locator('.chk-failed')).toHaveCount(1);
  await expect(page.getByTestId('edit-diff')).toBeVisible();
  await expect(page.locator('.dl-add').first()).toContainText('EUR 20,000');

  // 6. fix the edit -> executes
  await page.getByLabel('Body').fill(original.replace('Thursday morning', 'Thursday at 10:00 CET'));
  await page.getByRole('button', { name: 'Edit and approve', exact: true }).click();
  await expect(page.locator('.callout.ok', { hasText: 'Message handed to the simulated outreach provider' })).toBeVisible();
  await expect(page.getByTestId('edit-diff')).toHaveCount(2);

  // 7. reply, then intelligence updates
  await nav(page, 'Demo control');
  await page.getByRole('button', { name: 'Deliver scripted customer reply' }).click();
  await expect(page.getByText(/Scripted customer reply delivered/)).toBeVisible();
  await nav(page, 'Accounts');
  await page.getByRole('link', { name: 'Harbourline Freight Group' }).click();
  await expect(page.getByText('Jonas Weber').first()).toBeVisible();
  await expect(page.getByText(/v2 \//)).toBeVisible();
  await expect(page.getByText('Customer reply received (scripted)')).toBeVisible();

  // 8. audit verify OK then tamper
  await nav(page, 'Audit');
  await page.getByRole('button', { name: 'Verify chain' }).click();
  await expect(page.getByTestId('verify-ok')).toBeVisible();
  await page.getByRole('button', { name: /Tamper/ }).click();
  await page.getByRole('button', { name: 'Verify chain' }).click();
  await expect(page.getByTestId('verify-broken')).toContainText('BROKEN');

  // 9. evaluation honesty
  await nav(page, 'Evaluation');
  await expect(page.getByTestId('honest-statement')).toContainText('not real-world evidence');

  expect(errors).toEqual([]);
});

test('keyboard: reject needs a reason, reachable by keyboard', async ({ page }) => {
  await page.goto('/');
  await submitEnquiry(page);
  await nav(page, 'Approvals');
  await page.getByRole('link', { name: /^#301 / }).click();
  await page.getByLabel('Reject').focus();
  await page.keyboard.press('Space');
  await page.getByRole('button', { name: 'Reject', exact: true }).click();
  await expect(page.locator('select:invalid')).toHaveCount(1);
});
