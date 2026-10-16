// Headless end-to-end check of the UI with automated screenshots.
// Live mode: requests a ride for client C2 and follows it to completion.
// Replay mode: checks the recorded feed renders drivers and a ride.
// Usage: node tests/e2e.mjs <live|replay> <base_url> <screenshot_dir> <prefix>
import { chromium } from 'playwright';

const [mode = 'live', base = 'http://localhost:5173', outDir = '../proof/screenshots', prefix = 'ui'] = process.argv.slice(2);
const shot = (page, name) => page.screenshot({ path: `${outDir}/${prefix}-${name}.png` });
const t0 = Date.now();
const log = (m) => console.log(`${((Date.now() - t0) / 1000).toFixed(1).padStart(6)}s  ${m}`);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
await page.goto(base);

try {
  if (mode === 'live') {
    await page.getByTestId('conn').getByText('connected').waitFor({ timeout: 15000 });
    log('connected to WebSocket');
    await shot(page, '01-client-panel');
    await page.getByTestId('card-C2').click();
    await page.getByTestId('pickup').selectOption('Kilimani');
    await page.getByTestId('dropoff').selectOption('Upper Hill');
    await page.getByTestId('send').click();
    log('ride requested for C2 (Kilimani to Upper Hill)');
    await page.getByTestId('status-C2').getByText('Driver found').waitFor({ timeout: 20000 });
    log(`C2 status: ${await page.getByTestId('status-C2').innerText()}`);
    await shot(page, '02-driver-found');
    await page.getByTestId('tab-map').click();
    await page.getByTestId('driver-count').getByText('20 drivers').waitFor({ timeout: 10000 });
    await page.waitForFunction(() => Number(document.querySelector('[data-testid=active-rides]')?.textContent) >= 1, null, { timeout: 10000 });
    await page.waitForTimeout(3000);
    log('map shows 20 drivers and the active ride');
    await shot(page, '03-live-ops-map');
    await page.getByTestId('tab-clients').click();
    await page.getByTestId('status-C2').getByText('In trip').waitFor({ timeout: 240000 });
    log('C2 status: In trip');
    await page.getByTestId('status-C2').getByText('Completed').waitFor({ timeout: 300000 });
    log('C2 status: Completed');
    await shot(page, '04-completed');
  } else {
    await page.getByTestId('conn').getByText('Replay').waitFor({ timeout: 10000 });
    await page.getByTestId('tab-map').click();
    await page.getByTestId('driver-count').getByText('20 drivers').waitFor({ timeout: 15000 });
    log('replay: map shows 20 drivers');
    await page.waitForFunction(() => Number(document.querySelector('[data-testid=active-rides]')?.textContent) >= 1, null, { timeout: 30000 });
    await page.waitForTimeout(2000);
    log('replay: active ride drawn');
    await shot(page, 'replay-map');
    await page.getByTestId('tab-clients').click();
    log(`replay: C1 status ${await page.getByTestId('status-C1').innerText()}`);
  }
  if (errors.length) throw new Error(`page errors: ${errors.join(' | ')}`);
  log('PASS');
} catch (e) {
  await shot(page, 'failure');
  log(`FAIL: ${e.message}`);
  process.exitCode = 1;
} finally {
  await browser.close();
}
