// Renders diagram/index.html to diagram/architecture.png (1800 x 1000).
// Usage: node diagram/render.mjs   (PLAYWRIGHT_MODULE may point to an installed playwright package)
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? 'playwright');

const dir = path.dirname(fileURLToPath(import.meta.url));
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1800, height: 1000 } });
await page.goto(`file://${dir}/index.html`);
await page.waitForLoadState('networkidle');
await page.locator('#canvas').screenshot({ path: `${dir}/architecture.png` });
await browser.close();
