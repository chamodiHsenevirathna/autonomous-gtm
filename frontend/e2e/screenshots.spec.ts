import { test } from '@playwright/test';
import { driveStory, go, nav } from './helpers';

const ROUTES: [string, string][] = [
  ['overview', '#/'], ['leads', '#/leads'], ['accounts', '#/accounts'], ['account-detail', '#/accounts/201'], ['approvals', '#/approvals/302'],
  ['approvals-crm', '#/approvals/301'], ['runs', '#/runs'], ['run-trace', '#/runs/403'], ['alerts', '#/alerts'], ['audit', '#/audit'],
  ['evaluation', '#/evaluation'], ['feedback', '#/feedback'], ['demo', '#/demo'],
];
const DARK_SUBSET = new Set(['overview', 'account-detail', 'approvals', 'audit', 'evaluation', 'demo']);
const SIZES = { desktop: { width: 1280, height: 800 }, phone: { width: 390, height: 844 } } as const;

for (const theme of ['light', 'dark'] as const) {
  for (const [sizeName, size] of Object.entries(SIZES)) {
    test(`screenshots ${theme} ${sizeName}`, async ({ page }) => {
      await page.addInitScript((t) => { try { localStorage.setItem('gtm-theme', t); } catch { /* */ } }, theme);
      await page.setViewportSize(size);
      await driveStory(page);
      for (const [name, hash] of ROUTES) {
        if (theme === 'dark' && !DARK_SUBSET.has(name)) continue; // keep the folder small
        await go(page, hash);
        await page.waitForTimeout(250);
        await page.screenshot({ path: `screenshots/${name}.${theme}.${sizeName}.jpg`, type: 'jpeg', quality: 28, fullPage: true });
      }
      void nav;
    });
  }
}
