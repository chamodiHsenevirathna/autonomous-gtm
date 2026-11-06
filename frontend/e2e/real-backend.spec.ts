import { expect, test, type Page } from '@playwright/test';
import { nav } from './helpers';

/** Golden thread against the REAL backend (project `real-backend`). Ids and names come from the simulated world. */
async function openProposal(page: Page, type: RegExp) {
  await nav(page, 'Approvals');
  await page.getByRole('button', { name: 'All', exact: true }).click();
  await page.getByRole('link', { name: type }).first().click();
}

test('golden thread against the real backend', async ({ page }) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));

  await page.goto('/');
  await expect(page.locator('.clock time')).not.toHaveText('...');
  await expect(page.getByText('Mock API (browser fixtures)')).toHaveCount(0);
  // NOTE: GET /api/overview currently 500s on an empty database (BACKEND_MISMATCHES.md #17), so we do not assert on the first page here.

  await nav(page, 'Demo control');
  await page.getByRole('button', { name: 'Reset demo' }).click();
  await expect(page.getByText(/reset/i).first()).toBeVisible();
  await page.getByRole('button', { name: 'Submit scripted enquiry' }).click();
  await expect(page.getByText(/submitted and processed/)).toBeVisible();

  await nav(page, 'Overview');
  await expect(page.locator('.thread li.done').first()).toBeVisible();
  await nav(page, 'Leads');
  await expect(page.getByRole('cell', { name: /Marta Lindqvist/ })).toBeVisible();
  await expect(page.getByText('fit high 0.90')).toBeVisible(); // backend sends 0..100, UI normalises

  await nav(page, 'Accounts');
  await page.getByRole('link', { name: 'Brightwater Logistics' }).click();
  await expect(page.getByRole('heading', { name: 'Brightwater Logistics', level: 1 })).toBeVisible();
  await expect(page.locator('.chip', { hasText: /simulated/ }).first()).toBeVisible();
  await expect(page.getByText('AI-written').first()).toBeVisible();

  // CRM proposal
  await openProposal(page, /Crm write/);
  await expect(page.locator('.hash-full code')).toHaveText(/^[0-9a-f]{64}$/);
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Gateway and execution outcome' })).toBeVisible();
  await expect(page.locator('.checks li')).toHaveCount(13);
  await expect(page.locator('.chk-failed')).toHaveCount(0);

  // reply: edit with a price is refused by the real content screen
  await openProposal(page, /Message/);
  await expect(page.getByRole('heading', { name: 'Your decision' })).toBeVisible();
  await page.getByLabel('Edit and approve').check();
  const body = page.getByLabel('Body');
  const original = await body.inputValue();
  await body.fill(original + '\nOur fee would be EUR 20,000 fixed.');
  await page.getByRole('button', { name: 'Edit and approve', exact: true }).click();
  await expect(page.getByText('Blocked by the commercial-content screen.')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Gateway and execution outcome' })).toHaveCount(0);

  // edit-and-approve SUCCESS: a clean edit gets a new hash, shows a diff, and parks until time advances
  const hashBefore = await page.locator('.hash-full code').textContent();
  await body.fill(original + '\nThursday morning works well for us.');
  await page.getByRole('button', { name: 'Edit and approve', exact: true }).click();
  await expect(page.getByText('Parked, not failed.')).toBeVisible();
  await expect(page.getByTestId('edit-diff')).toBeVisible();
  await expect(page.locator('.dl-add').first()).toContainText('Thursday morning works well');
  expect(await page.locator('.hash-full code').textContent()).not.toBe(hashBefore);

  await nav(page, 'Demo control');
  await page.getByRole('button', { name: 'Advance +1 hour' }).click();
  await expect(page.getByText(/Advanced the simulated clock/)).toBeVisible();
  await openProposal(page, /Message/);
  await expect(page.locator('.callout.ok', { hasText: /sent to/ })).toBeVisible();

  await nav(page, 'Demo control');
  await page.getByRole('button', { name: 'Deliver scripted customer reply' }).click();
  await expect(page.getByText(/arrived and was processed/)).toBeVisible();
  await nav(page, 'Accounts');
  await page.getByRole('link', { name: 'Brightwater Logistics' }).click();
  await expect(page.getByText('Marta Lindqvist is interested').first()).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Stakeholders' })).toBeVisible();
  await expect(page.getByText('Customer open to a call')).toBeVisible();
  await expect(page.getByText('Re: your note').first()).toBeVisible();

  // reject with a reason: the follow-up task proposal created by the reply
  await nav(page, 'Approvals');
  await page.getByRole('link', { name: /Task/ }).first().click();
  await page.getByLabel('Reject').check();
  await page.getByLabel(/Reason code/).selectOption('not_ready');
  await page.getByLabel(/Comment/).fill('Too early to assign.');
  await page.getByRole('button', { name: 'Reject', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Decision record' })).toBeVisible();
  await expect(page.getByText('Too early to assign.')).toBeVisible();
  // (the real backend does not turn reviewer comments into Feedback items, unlike the mock; see BACKEND_MISMATCHES.md)
  await nav(page, 'Feedback');
  await expect(page.getByRole('heading', { name: 'Feedback items' })).toBeVisible();

  await nav(page, 'Audit');
  await page.getByRole('button', { name: 'Verify chain' }).click();
  await expect(page.getByTestId('verify-ok')).toBeVisible();
  expect(errors).toEqual([]);
});
