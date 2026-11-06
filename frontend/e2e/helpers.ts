import { expect, type Page } from '@playwright/test';

export const go = (page: Page, hash: string) => page.evaluate((h) => { location.hash = h; }, hash);
export async function nav(page: Page, name: string) {
  const link = page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name, exact: true });
  await link.click();
}

export async function submitEnquiry(page: Page) {
  await nav(page, 'Demo control');
  await page.getByRole('button', { name: 'Submit scripted enquiry' }).click();
  await expect(page.getByText(/Enquiry submitted\./)).toBeVisible();
}

export async function approveFromQueue(page: Page, id: number) {
  await nav(page, 'Approvals');
  await page.getByRole('link', { name: new RegExp(`^#${id} `) }).click();
  await expect(page.getByRole('heading', { name: new RegExp(`Proposal #${id}:`) })).toBeVisible();
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Gateway and execution outcome' })).toBeVisible();
}

/** Drives the whole story with UI clicks only (state lives in the page, so never reload). */
export async function driveStory(page: Page) {
  await page.goto('/');
  await submitEnquiry(page);
  await approveFromQueue(page, 301);
  await approveFromQueue(page, 302);
  await nav(page, 'Demo control');
  await page.getByRole('button', { name: 'Deliver scripted customer reply' }).click();
  await expect(page.getByText(/Scripted customer reply delivered/)).toBeVisible();
  await page.getByRole('button', { name: 'Advance +3 days' }).click();
  await expect(page.getByText(/Simulated clock advanced/).first()).toBeVisible();
}
