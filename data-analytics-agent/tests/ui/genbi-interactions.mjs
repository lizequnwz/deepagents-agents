/** First GenBI interaction increment, using the real API and saved evidence. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const require = createRequire(path.join(root, 'frontend/package.json'));
const { chromium, expect } = require('@playwright/test');
const args = process.argv.slice(2);
const arg = (name, fallback) => args.includes(name) ? args[args.indexOf(name) + 1] : fallback;
const output = path.resolve(arg('--output', path.join(root, 'frontend/test-results/genbi-interactions')));
const frontend = path.resolve(arg('--frontend-root', path.join(root, 'frontend')));
const storage = path.join(output, 'storage');
const port = Number(arg('--api-port', '8798'));
const base = `http://127.0.0.1:${port}`;
fs.mkdirSync(output, { recursive: true });
const scenarios = [], pageErrors = [], consoleErrors = [], expectedNetworkErrors = [];
const allowedConnectionFailures = new Map();
let api, browser;
async function json(url, init = {}) {
  const response = await fetch(base + url, { ...init, headers: { 'Content-Type': 'application/json', ...init.headers } });
  const body = await response.json();
  if (!response.ok) throw new Error(`${response.status}: ${JSON.stringify(body)}`);
  return body;
}
async function scenario(name, action) {
  try { const details = await action(); scenarios.push({ name, status: 'pass', ...details }); process.stdout.write(`PASS ${name}\n`); }
  catch (error) { scenarios.push({ name, status: 'fail', error: String(error.stack || error) }); process.stdout.write(`FAIL ${name}: ${error.message}\n`); }
}
async function chartReady(page) {
  await expect(page.locator('.js-plotly-plot').first()).toBeVisible();
  await expect(page.locator('.chart-skeleton')).toHaveCount(0);
}

try {
  const log = fs.openSync(path.join(output, 'api.log'), 'w');
  api = spawn(path.join(root, '.venv/bin/python'), ['-m', 'tests.ui.server', '--storage', storage, '--port', String(port), '--frontend-root', frontend], {
    cwd: root, env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' }, stdio: ['ignore', log, log],
  });
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    if (api.exitCode !== null) throw new Error(`Fixture failed (${api.exitCode}).`);
    try { if ((await fetch(base + '/health')).ok) break; } catch {}
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  const manifest = JSON.parse(fs.readFileSync(path.join(storage, 'ui-manifest.json'), 'utf8'));
  const endpoint = `/api/conversations/${manifest.thread_id}/dashboards`;
  let board = await json(endpoint, { method: 'POST', body: JSON.stringify({ run_id: manifest.run_id, title: 'Interactive sales', request_id: 'genbi-interactions' }) });
  const chartComponent = board.components.find(component => component.type === 'chart');
  const tableComponent = board.components.find(component => component.type === 'table');
  const bindings = board.components.filter(component => component.type === 'chart' || component.type === 'table').map(component => ({ component_id: component.id, column: 'region' }));
  board = await json(`${endpoint}/${board.revision.dashboard_id}/view`, { method: 'POST', body: JSON.stringify({
    expected_revision: board.revision.revision_id, request_id: 'genbi-interaction-filters', filters: [
      { id: 'region', label: 'Sales region', kind: 'category', bindings },
      { id: 'month', label: 'Observation month', kind: 'category', bindings: [{ component_id: chartComponent.id, column: 'month' }] },
      { id: 'sales_value', label: 'Observed sales value', kind: 'category', bindings: [{ component_id: tableComponent.id, column: 'sales' }] },
    ],
  }) });
  const chrome = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  browser = await chromium.launch({ headless: true, executablePath: fs.existsSync(chrome) ? chrome : undefined });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('console', event => {
    if (event.type() !== 'error') return;
    const url = event.location().url;
    if (event.text().includes('ERR_CONNECTION_RESET') && allowedConnectionFailures.get(url)) {
      allowedConnectionFailures.delete(url);
      expectedNetworkErrors.push({ url, message: event.text() });
    } else consoleErrors.push(event.text());
  });
  const dashboardUrl = `${base}/workspace/?thread=${manifest.thread_id}&dashboard=${board.revision.dashboard_id}`;
  await page.goto(dashboardUrl);
  await chartReady(page);

  await scenario('Evidence inspection opens the saved dataset without an analytical run', async () => {
    const before = (await json(`/api/conversations/${manifest.thread_id}`)).run_ids;
    const panel = page.getByRole('region', { name: 'Dashboard evidence', exact: true });
    await panel.getByText('Evidence and saved values', { exact: true }).click();
    const inspection = page.waitForResponse(response => response.url().includes('/api/results/') && response.url().includes('limit=10'));
    await panel.getByRole('button', { name: 'Inspect saved data', exact: true }).first().click();
    expect((await inspection).status()).toBe(200);
    await expect(panel.getByRole('table')).toBeVisible();
    await expect(panel.getByText('Preview: at most 10 of 4 saved rows.', { exact: true })).toBeVisible();
    expect((await json(`/api/conversations/${manifest.thread_id}`)).run_ids).toEqual(before);
    await panel.getByRole('button', { name: 'Close saved data', exact: true }).click();
    return { saved_evidence_action: true, saved_rows_shown: 4, analytical_runs_added: 0 };
  });

  await scenario('Multiple draft values persist without source execution', async () => {
    const requests = [];
    const record = request => { if (request.method() === 'POST' && request.url().endsWith('/actions')) requests.push(request.postDataJSON()); };
    page.on('request', record);
    const select = page.getByLabel('Sales region', { exact: true });
    await select.selectOption([{ label: 'North' }, { label: 'South' }]);
    await expect(select).toHaveValues(['"North"', '"South"']);
    await expect(page.getByText('1 unapplied filter change', { exact: true })).toBeVisible();
    const numericSelect = page.getByLabel('Observed sales value', { exact: true });
    await numericSelect.selectOption(['100', '120']);
    await expect(numericSelect).toHaveValues(['100', '120']);
    await page.getByRole('button', { name: 'Edit view', exact: true }).click();
    await page.getByRole('button', { name: 'Save view', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Edit the saved view', exact: true })).toHaveCount(0);
    await page.reload();
    await chartReady(page);
    await expect(select).toHaveValues(['"North"', '"South"']);
    const saved = await json(`${endpoint}/${board.revision.dashboard_id}`);
    expect(saved.revision.saved_filter_values.region).toEqual(['North', 'South']);
    expect(saved.revision.saved_filter_values.sales_value).toEqual([100, 120]);
    expect(saved.revision.applied_filters).toEqual({});
    expect(requests).toEqual([]);
    const filterField = select.locator('..');
    await filterField.getByText('Search saved values', { exact: true }).click();
    await filterField.getByLabel('Search saved Sales region', { exact: true }).fill('Sou');
    await filterField.getByRole('button', { name: 'Find values', exact: true }).click();
    await expect(filterField.getByText('1 saved value found.', { exact: true })).toBeVisible();
    await expect(select).toHaveValues(['"North"', '"South"']);
    expect(requests).toEqual([]);
    await select.selectOption('');
    await numericSelect.selectOption('');
    await expect(page.getByRole('button', { name: 'Apply filters', exact: true })).toBeDisabled();
    page.off('request', record);
    return { multiple_values_restored: true, numeric_values_keep_type: true, saved_value_search_keeps_draft: true, applied_values_unchanged: true, analytical_runs: requests.length };
  });

  await scenario('Chart click and keyboard selection send exact evidence context', async () => {
    const runsBefore = (await json(`/api/conversations/${manifest.thread_id}`)).run_ids;
    let connectionAttempts = 0;
    let interruptedUrl;
    const streamPattern = `**/api/conversations/${manifest.thread_id}/runs/*/events`;
    await page.route(streamPattern, async route => {
      const url = route.request().url();
      if (url.includes(`/runs/${manifest.run_id}/events`)) return route.continue();
      connectionAttempts++;
      if (!interruptedUrl) {
        interruptedUrl = url;
        allowedConnectionFailures.set(url, true);
        return route.abort('connectionreset');
      }
      return route.continue();
    });
    const point = page.locator('.scatterlayer .points .point').first();
    await point.scrollIntoViewIfNeeded();
    const bounds = await point.boundingBox();
    if (!bounds) throw new Error('The chart point has no visible bounds.');
    // Plotly's transparent drag surface receives pointer events over the marks.
    await page.mouse.click(bounds.x + bounds.width / 2, bounds.y + bounds.height / 2);
    await expect(page.getByText('Selected Observation month: 2026-01', { exact: true })).toBeVisible();
    const values = page.getByLabel('Select Observation month to investigate', { exact: true });
    await values.focus();
    await expect(values).toBeFocused();
    await values.selectOption(['"2026-01"', '"2026-02"']);
    await expect(values).toHaveValues(['"2026-01"', '"2026-02"']);
    const request = page.waitForRequest(request => request.method() === 'POST' && request.url().endsWith('/actions'));
    const response = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/actions'));
    await page.getByRole('button', { name: 'Compare selection', exact: true }).click();
    const payload = (await request).postDataJSON();
    const action = await (await response).json();
    expect(payload.action).toBe('drill');
    expect(payload.component_id).toBe(chartComponent.id);
    expect(payload.selection).toEqual({ result_id: chartComponent.analysis_result_id, column: 'month', values: ['2026-01', '2026-02'] });
    await expect.poll(() => connectionAttempts, { timeout: 15_000 }).toBeGreaterThanOrEqual(2);
    const runDeadline = Date.now() + 15_000;
    let updated;
    while (Date.now() < runDeadline) {
      updated = await json(`${endpoint}/${board.revision.dashboard_id}`);
      if (updated.pending_action?.status !== 'running' && updated.pending_action?.status !== 'queued') break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    expect(updated.revision.applied_filters).toEqual({});
    const conversation = await json(`/api/conversations/${manifest.thread_id}`);
    expect(conversation.run_ids).toEqual([...runsBefore, action.run_id]);
    expect(conversation.turns.filter(turn => turn.run_id === action.run_id)).toHaveLength(1);
    await page.unroute(streamPattern);
    return { typed_point_selection: true, real_pointer_click: true, keyboard_list: true, applied_filters_unchanged: true,
      stream_connection_interrupted_once: true, stream_connection_attempts: connectionAttempts, analytical_runs_added: 1, duplicate_turns: 0 };
  });

  await scenario('Completed findings edits commit chart and report without an analytical run', async () => {
    await page.goto(`${base}/workspace/?thread=${manifest.thread_id}`);
    await chartReady(page);
    const runsBefore = (await json(`/api/conversations/${manifest.thread_id}`)).run_ids;
    await page.getByRole('button', { name: 'Edit chart', exact: true }).first().click();
    const editor = page.getByRole('form', { name: 'Edit Monthly sales by region', exact: true });
    await editor.getByLabel('Chart title', { exact: true }).fill('Reviewed sales chart');
    await editor.getByLabel('X-axis label', { exact: true }).fill('Observation month');
    await editor.getByLabel('Y-axis label', { exact: true }).fill('Sales in source units');
    await editor.getByLabel('Color palette', { exact: true }).selectOption('blues');
    const save = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/presentation'));
    await editor.getByRole('button', { name: 'Save chart', exact: true }).click();
    const response = await save;
    expect(response.status()).toBe(200);
    const answer = await response.json();
    expect(answer.charts[0].title).toBe('Reviewed sales chart');
    expect(answer.charts[0].palette).toBe('blues');
    await expect(page.getByRole('heading', { name: 'Reviewed sales chart', exact: true })).toBeVisible();
    await chartReady(page);
    await page.reload();
    await chartReady(page);
    await expect(page.getByRole('heading', { name: 'Reviewed sales chart', exact: true })).toBeVisible();
    const conversation = await json(`/api/conversations/${manifest.thread_id}`);
    expect(conversation.run_ids).toEqual(runsBefore);
    return { chart_and_report_saved: true, restart_view_retained: true, analytical_runs_added: 0 };
  });

  await scenario('New controls fit a phone and retain visible labels', async () => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(dashboardUrl);
    await chartReady(page);
    await expect(page.getByLabel('Sales region', { exact: true })).toBeVisible();
    await expect(page.getByLabel('Select Observation month to investigate', { exact: true })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await page.screenshot({ path: path.join(output, 'phone-selection.png'), fullPage: true });
    return { phone_width: 375, no_horizontal_overflow: true };
  });
} catch (error) {
  scenarios.push({ name: 'Test setup', status: 'fail', error: String(error.stack || error) });
} finally {
  await browser?.close();
  api?.kill('SIGTERM');
  const receipt = { tested_at: new Date().toISOString(), scenarios, page_errors: pageErrors, console_errors: consoleErrors, expected_network_errors: expectedNetworkErrors, real_api: true, model_provider_calls: 0,
    status: scenarios.length > 0 && scenarios.every(scenario => scenario.status === 'pass') && !pageErrors.length && !consoleErrors.length ? 'pass' : 'fail' };
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
  if (receipt.status !== 'pass') process.exitCode = 1;
}
