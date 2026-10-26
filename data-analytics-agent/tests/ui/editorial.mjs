/** Editorial dashboard visual QA over isolated saved analytical fixtures. */
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const require = createRequire(path.join(root, 'frontend/package.json'));
const { chromium, expect } = require('@playwright/test');
const args = process.argv.slice(2);
const arg = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback;
const output = path.resolve(arg('--output', '/tmp/analytics-editorial-qa'));
const frontend = path.resolve(arg('--frontend-root', path.join(root, 'frontend')));
const port = Number(arg('--api-port', '8828'));
const base = `http://127.0.0.1:${port}`;
const storage = path.join(output, 'storage');
fs.mkdirSync(output, { recursive: true });
let service, browser;
const errors = [], checks = {};
async function json(url, body) {
  const response = await fetch(base + url, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {});
  const result = await response.json();
  if (!response.ok) throw new Error(`${response.status}: ${JSON.stringify(result)}`);
  return result;
}
try {
  const log = fs.openSync(path.join(output, 'service.log'), 'w');
  // A floating-point tail is real saved fixture data, not an intercepted display.
  const bootstrap = 'from tests.ui import server; server.SALES[0]["sales"] = 0.30000000000000004; server.main()';
  service = spawn(path.join(root, '.venv/bin/python'), ['-c', bootstrap, '--storage', storage, '--port', String(port), '--frontend-root', frontend], {
    cwd: root, stdio: ['ignore', log, log], env: { ...process.env, LANGSMITH_TRACING: 'false' },
  });
  for (let attempt = 0; attempt < 200; attempt++) {
    if (service.exitCode !== null) throw new Error(`Fixture exited (${service.exitCode}).`);
    try { if ((await fetch(base + '/health')).ok) break; } catch {}
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  const manifest = JSON.parse(fs.readFileSync(path.join(storage, 'ui-manifest.json'), 'utf8'));
  const endpoint = `/api/conversations/${manifest.thread_id}/dashboards`;
  const board = await json(endpoint, { run_id: manifest.run_id, request_id: 'editorial-visual', spec: {
    title: 'A closer look at regional sales',
    description: 'Monthly sales observations for North and South. Values use source units; source completeness is unknown.',
    components: [
      { id: 'observation', type: 'metric', span: 1, metric: { label: 'North · January', result_id: manifest.result_id, column: 'sales', row_index: 0, number_format: ',.2f', context: 'One saved monthly observation · source units' } },
      { id: 'monthly-sales', type: 'chart', chart_id: manifest.chart_id, span: 3 },
      { id: 'supporting-data', type: 'table', result_id: manifest.result_id, title: 'The observations behind the chart', span: 3 },
    ], filters: [],
  } });
  const chrome = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  browser = await chromium.launch({ headless: true, executablePath: fs.existsSync(chrome) ? chrome : undefined });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  page.on('pageerror', error => errors.push(error.message));
  const url = `${base}/workspace/?thread=${manifest.thread_id}&dashboard=${board.revision.dashboard_id}`;
  await page.goto(url);
  await expect(page.locator('.js-plotly-plot')).toBeVisible();
  await expect(page.locator('.chart-skeleton')).toHaveCount(0);
  await expect(page.locator('.work-area')).toHaveClass(/chat-hidden/);
  const title = await page.locator('.dashboard-heading h2').boundingBox();
  const metric = await page.locator('.widget-metric').boundingBox();
  const chart = await page.locator('.widget-chart').boundingBox();
  expect(title.y).toBeLessThan(240);
  expect(metric.y).toBeLessThan(430);
  expect(chart.y).toBeLessThan(650);
  await expect(page.locator('.analytical-evidence')).not.toHaveAttribute('open');
  const exact = page.getByTitle('Exact stored value: 0.30000000000000004', { exact: true });
  await expect(exact).toHaveText('0.3');
  await exact.focus();
  await expect(exact).toBeFocused();
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({ path: path.join(output, 'desktop-first-screen.png'), fullPage: false });
  await page.screenshot({ path: path.join(output, 'desktop-light.png'), fullPage: true });
  checks.desktop = { title, metric, chart, exact_value_tooltip: true, canvas_focused: true };
  await page.getByRole('button', { name: 'Use dark theme', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await expect(page.locator('.new-workspace')).toHaveCSS('background-color', 'rgb(41, 41, 40)');
  await page.screenshot({ path: path.join(output, 'desktop-dark.png'), fullPage: true });
  await page.getByRole('button', { name: 'Use light theme', exact: true }).click();
  await page.locator('.metric-format > summary').click();
  await page.getByLabel('Number format for North · January', { exact: true }).selectOption(',.4f');
  await page.getByRole('button', { name: 'Save format', exact: true }).click();
  await expect(page.locator('.widget-metric .metric-value')).toHaveText('0.3000');
  const revised = await json(`${endpoint}/${board.revision.dashboard_id}`);
  expect(revised.revision.report_id).not.toBe(board.revision.report_id);
  expect(revised.components.find(component => component.id === 'observation').value).toBe(0.30000000000000004);
  checks.metric_format = { matching_report_revised: true, source_value_unchanged: true };
  await page.getByRole('button', { name: 'Edit view', exact: true }).click();
  await page.getByLabel('Width for North · January', { exact: true }).selectOption('2');
  await page.getByRole('button', { name: 'Save view', exact: true }).click();
  await expect(page.locator('.widget-metric')).toHaveClass(/span-2/);
  await expect(page.locator('.metric-strip')).toHaveCount(0);
  await page.getByRole('button', { name: 'Edit view', exact: true }).click();
  await page.getByLabel('Width for North · January', { exact: true }).selectOption('1');
  await page.getByRole('button', { name: 'Save view', exact: true }).click();
  checks.explicit_metric_width = true;
  await page.setViewportSize({ width: 375, height: 812 });
  await page.reload();
  await expect(page.locator('.js-plotly-plot')).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
  await page.screenshot({ path: path.join(output, 'phone-light.png'), fullPage: true });
  checks.phone = { width: 375, no_horizontal_overflow: true };
  await page.goto(`${base}/workspace/?thread=${manifest.review_thread_id}`);
  await expect(page.getByRole('heading', { name: 'Review the proposed calculation', exact: true })).toBeVisible();
  checks.required_review_visible = true;
} catch (error) {
  errors.push(String(error.stack || error));
} finally {
  await browser?.close();
  service?.kill('SIGTERM');
  const receipt = { tested_at: new Date().toISOString(), checks, errors, model_provider_calls: 0, status: Object.keys(checks).length && !errors.length ? 'pass' : 'fail' };
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
  process.stdout.write(JSON.stringify(receipt, null, 2) + '\n');
  if (receipt.status !== 'pass') process.exitCode = 1;
}
