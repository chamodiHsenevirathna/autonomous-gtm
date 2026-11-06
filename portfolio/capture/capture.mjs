// Drives the golden thread against the real running app (http mode, real backend).
// MODE=shots  -> 1440x900 @2x PNG screenshots into ../screenshots
// MODE=video  -> 1280x800 continuous recording into ../demo
import { createRequire } from 'module';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';
const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, '../../frontend/package.json'));
const { chromium, expect } = require('@playwright/test');

const MODE = process.env.MODE || 'shots';
const BASE = process.env.BASE_URL || 'http://localhost:5174';
const VIDEO = MODE === 'video';
const OUT = path.join(here, '../screenshots');
const DEMO = path.join(here, '../demo');
const marks = [];
const t0 = Date.now();
const mark = (label) => { marks.push([((Date.now() - t0) / 1000).toFixed(1), label]); console.log(marks.at(-1).join('s  ')); };

const browser = await chromium.launch();
const ctxOpts = VIDEO
  ? { viewport: { width: 1280, height: 800 }, recordVideo: { dir: path.join(DEMO, 'raw'), size: { width: 1280, height: 800 } } }
  : { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 };
const ctx = await browser.newContext({ ...ctxOpts, colorScheme: 'light' });
const page = await ctx.newPage();
const problems = [];
page.on('pageerror', (e) => problems.push('pageerror: ' + e.message));
page.on('console', (m) => { if (m.type() === 'error') problems.push('console: ' + m.text()); });

const pause = (ms) => page.waitForTimeout(VIDEO ? ms : 150);
async function settle() {
  await page.waitForLoadState('networkidle').catch(() => {});
  await expect(page.locator('.spinner')).toHaveCount(0);
  await expect(page.getByText(/^Loading /)).toHaveCount(0);
  await page.waitForTimeout(250);
}
async function shot(name, { full = false, maxH = 2600 } = {}) {
  if (VIDEO) return;
  await settle();
  const opts = { path: path.join(OUT, name + '.png') };
  if (full) {
    // The app lays out with a sticky shell, so fullPage stitching tears. Grow the viewport instead.
    await page.setViewportSize({ width: 1440, height: 900 });
    let h = await page.evaluate(() => Math.max(document.documentElement.scrollHeight, document.querySelector('main')?.scrollHeight ?? 0));
    h = Math.min(Math.max(h, 900), maxH);
    await page.setViewportSize({ width: 1440, height: h });
    await page.waitForTimeout(300);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot(opts);
    await page.setViewportSize({ width: 1440, height: 900 });
  } else await page.screenshot(opts);
  console.log('saved', name);
}
const nav = async (name) => { await page.getByRole('navigation', { name: 'Main' }).getByRole('link', { name, exact: true }).click(); await settle(); };
async function openProposal(type) {
  await nav('Approvals');
  await page.getByRole('button', { name: 'All', exact: true }).click();
  await page.getByRole('link', { name: type }).first().click();
  await settle();
}

try {
  await page.goto(BASE + '/');
  await expect(page.locator('.clock time')).not.toHaveText('...');
  await nav('Demo control');
  await page.getByRole('button', { name: 'Reset demo' }).click();
  await expect(page.getByText(/reset/i).first()).toBeVisible();
  await pause(2500); mark('Demo control: clean reset state');
  await shot('02-demo-control-pre'.replace('-pre', '')); // overwritten later by post-story? keep this one (fresh state)
  await page.getByRole('button', { name: 'Submit scripted enquiry' }).click();
  await expect(page.getByText(/submitted and processed/)).toBeVisible();
  await pause(3000); mark('Scripted enquiry submitted and processed');
  await shot('02-demo-control');

  await nav('Leads'); await expect(page.getByRole('cell', { name: /Marta Lindqvist/ })).toBeVisible();
  await pause(3500); mark('Leads: new lead scored'); await shot('03-leads');

  await nav('Accounts');
  await page.getByRole('link', { name: 'Brightwater Logistics' }).click();
  await expect(page.getByRole('heading', { name: 'Brightwater Logistics', level: 1 })).toBeVisible(); await settle();
  await pause(3000); mark('Account: provenance, conflict flags, AI-written, agent state');
  await shot('10-account-before-reply', { full: true });
  if (VIDEO) { await page.mouse.wheel(0, 700); await pause(2500); await page.mouse.wheel(0, 700); await pause(2500); }

  await nav('Approvals'); await pause(2000); mark('Approvals queue'); await shot('11-approvals-list');
  await openProposal(/Crm write/);
  await pause(3000); mark('CRM proposal: payload and SHA-256 hash'); 
  if (VIDEO) { await page.mouse.wheel(0, 500); await pause(2500); }
  await page.getByRole('button', { name: 'Approve', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Gateway and execution outcome' })).toBeVisible();
  await expect(page.locator('.checks li')).toHaveCount(13);
  await page.locator('.checks').scrollIntoViewIfNeeded(); await pause(3500); mark('CRM approved: 13 gateway checks');
  await shot('05-approval-crm', { full: true });

  await openProposal(/Message/);
  await page.getByLabel('Edit and approve').check();
  const body = page.getByLabel('Body');
  const original = await body.inputValue();
  await body.fill(original + '\nOur fee would be EUR 20,000 fixed.');
  await pause(2500); mark('Reply edited to include a price');
  await page.getByRole('button', { name: 'Edit and approve', exact: true }).click();
  await expect(page.getByText('Blocked by the commercial-content screen.')).toBeVisible();
  await page.getByText('Blocked by the commercial-content screen.').scrollIntoViewIfNeeded();
  await pause(3500); mark('Blocked by the commercial-content screen');
  await shot('06-approval-edit-blocked', { full: true });

  await body.fill(original + '\nThursday morning works well for us.');
  await page.getByRole('button', { name: 'Edit and approve', exact: true }).click();
  await expect(page.getByText('Parked, not failed.')).toBeVisible();
  await expect(page.getByTestId('edit-diff')).toBeVisible();
  await page.getByTestId('edit-diff').scrollIntoViewIfNeeded(); await pause(3500); mark('Clean edit approved: diff, new hash, send parked');
  await shot('12-approval-edit-diff', { full: true });

  await nav('Demo control');
  await page.getByRole('button', { name: 'Advance +1 hour' }).click();
  await expect(page.getByText(/Advanced the simulated clock/)).toBeVisible();
  await pause(2500); mark('Clock advanced +1 hour');
  await openProposal(/Message/);
  await expect(page.locator('.callout.ok', { hasText: /sent to/ })).toBeVisible();
  await pause(2500); mark('Parked send executed');

  await nav('Demo control');
  await page.getByRole('button', { name: 'Deliver scripted customer reply' }).click();
  await expect(page.getByText(/arrived and was processed/)).toBeVisible();
  await pause(2500); mark('Scripted customer reply delivered');

  await nav('Accounts');
  await page.getByRole('link', { name: 'Brightwater Logistics' }).click();
  await expect(page.getByText('Marta Lindqvist is interested').first()).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Stakeholders' })).toBeVisible(); await settle();
  await pause(3500); mark('Account intelligence updated'); await shot('04-account-intelligence', { full: true });
  if (VIDEO) { await page.mouse.wheel(0, 800); await pause(2500); }

  await nav('Runs'); await settle(); await pause(2000);
  await page.locator('tbody tr a').first().click(); await page.locator('.trace li').first().waitFor(); await settle();
  await pause(3500); mark('Workflow run step trace'); await shot('07-run-trace', { full: true });

  await nav('Audit');
  await page.getByRole('button', { name: 'Verify chain' }).click();
  await expect(page.getByTestId('verify-ok')).toBeVisible();
  await pause(3500); mark('Audit: chain verification OK'); await shot('08-audit-verify', { full: true });

  await nav('Evaluation');
  await page.getByRole('button', { name: 'Re-run evaluation' }).click();
  await page.getByText(/[1-9]\d* of \d+ scenarios pass/).waitFor({ timeout: 120000 }); await settle();
  await pause(4000); mark('Evaluation results'); await shot('09-evaluation', { full: true });

  await nav('Feedback'); await pause(2000); await shot('14-feedback');
  await nav('Overview'); await page.locator('.thread li.done').first().waitFor(); await pause(3500); mark('Overview'); await shot('01-overview', { full: true });

  // dark variants of core screens
  if (!VIDEO) {
    await page.evaluate(() => { document.documentElement.dataset.theme = 'dark'; });
    await shot('15-overview-dark', { full: true });
    await nav('Evaluation'); await shot('16-evaluation-dark', { full: true });
    await nav('Audit'); await shot('17-audit-dark', { full: true });
  }
} catch (e) {
  console.error('FAILED', e); process.exitCode = 1;
  if (!VIDEO) await page.screenshot({ path: path.join(here, 'failure.png') });
}
console.log('page problems:', problems);
fs.writeFileSync(path.join(here, VIDEO ? 'video-marks.json' : 'shot-problems.json'), JSON.stringify(VIDEO ? marks : problems, null, 1));
const v = page.video();
await ctx.close(); await browser.close();
if (VIDEO && v) { fs.mkdirSync(DEMO, { recursive: true }); fs.copyFileSync(await v.path(), path.join(DEMO, 'golden-thread.webm')); fs.rmSync(path.join(DEMO, 'raw'), { recursive: true, force: true }); }
