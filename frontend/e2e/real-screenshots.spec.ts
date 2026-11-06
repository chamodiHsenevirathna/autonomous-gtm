import { expect, test, type Page } from '@playwright/test';
import { go, nav } from './helpers';

const ROUTES: [string, string, string][] = [
  // name, hash, selector that proves real content has rendered
  ['overview', '#/', '.thread li.done'],
  ['leads', '#/leads', 'tbody tr'],
  ['accounts', '#/accounts', 'tbody tr'],
  ['account', '#/accounts/1', '#agent-h'],
  ['approvals', '#/approvals', '.queue li'],
  ['runs', '#/runs', 'tbody tr'],
  ['run-trace', '#/runs/1', '.trace li'],
  ['audit', '#/audit', 'table.audit tbody tr'],
  ['evaluation', '#/evaluation', '.basis-key li'],
  ['feedback', '#/feedback', '#items-h'],
  ['alerts', '#/alerts', 'h1'],
  ['demo', '#/demo', '.bigclock'],
];
const COMBOS = [
  { name: 'light.desktop', theme: 'light', size: { width: 1280, height: 800 }, all: true },
  { name: 'light.phone', theme: 'light', size: { width: 390, height: 844 }, all: true },
  { name: 'dark.desktop', theme: 'dark', size: { width: 1280, height: 800 }, all: false },
] as const;
const DARK = new Set(['overview', 'account', 'approvals', 'evaluation', 'audit']);

async function settled(page: Page, selector: string) {
  await page.locator(selector).first().waitFor({ timeout: 30_000 });
  await expect(page.locator('.spinner')).toHaveCount(0);
  await expect(page.getByText(/^Loading /)).toHaveCount(0);
}

test('real-data screenshots (taken after content has loaded)', async ({ page }) => {
  test.setTimeout(300_000);
  await page.goto('/');
  await nav(page, 'Demo control');
  await page.getByRole('button', { name: 'Reset demo' }).click();
  await page.getByRole('button', { name: 'Submit scripted enquiry' }).click();
  await page.getByText(/submitted and processed/).waitFor();
  for (const type of [/Crm write/, /Message/]) {
    await nav(page, 'Approvals');
    await page.getByRole('button', { name: 'All', exact: true }).click();
    await page.getByRole('link', { name: type }).first().click();
    await page.getByRole('button', { name: 'Approve', exact: true }).click();
    await page.getByRole('heading', { name: 'Gateway and execution outcome' }).waitFor();
  }
  await nav(page, 'Demo control');
  await page.getByRole('button', { name: 'Advance +1 hour' }).click();
  await page.getByText(/Advanced the simulated clock/).waitFor();
  await page.getByRole('button', { name: 'Deliver scripted customer reply' }).click();
  await page.getByText(/arrived and was processed/).waitFor();
  await nav(page, 'Evaluation');
  await page.getByRole('button', { name: 'Re-run evaluation' }).click();
  await page.getByText(/[1-9]\d* of \d+ scenarios pass/).waitFor({ timeout: 120_000 });

  for (const c of COMBOS) {
    await page.evaluate((t) => { document.documentElement.dataset.theme = t; }, c.theme);
    await page.setViewportSize(c.size);
    for (const [name, hash, sel] of ROUTES) {
      if (!c.all && !DARK.has(name)) continue;
      await go(page, hash);
      await settled(page, sel);
      await page.waitForTimeout(200);
      const h = await page.evaluate(() => document.documentElement.scrollHeight);
      await page.screenshot({ path: `screenshots/real/${name}.${c.name}.jpg`, type: 'jpeg', quality: 30, fullPage: true,
        clip: { x: 0, y: 0, width: c.size.width, height: Math.min(h, name === 'evaluation' ? 1800 : 2600) } });
    }
  }
});
