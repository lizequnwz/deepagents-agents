/** Full-browser checks against the real application and isolated local evidence. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';
import { spawn } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const require = createRequire(path.join(root, 'frontend/package.json'));
const { chromium, expect } = require('@playwright/test');
const args = process.argv.slice(2);
const arg = (name, fallback) => {
  const index = args.indexOf(name);
  return index < 0 ? fallback : args[index + 1];
};
const apiPort = Number(arg('--api-port', '8780'));
const streamlitPort = Number(arg('--streamlit-port', '8781'));
const base = arg('--base-url', `http://127.0.0.1:${apiPort}`);
const output = path.resolve(arg('--output', path.join(root, 'frontend/test-results/ui')));
const frontendRoot = path.resolve(arg('--frontend-root', path.join(root, 'frontend')));
const storage = path.join(output, 'storage');
fs.mkdirSync(output, { recursive: true });
const owned = [];
const results = [];
const errors = [];
const consoleErrors = [];
const httpErrors = [];
let browser;
let browserVersion;
let savedDashboardId;
let importedThreadId;

function launch(label, command, commandArgs, env = {}) {
  const log = fs.openSync(path.join(output, `${label}.log`), 'w');
  const child = spawn(command, commandArgs, {
    cwd: root,
    env: { ...process.env, ...env },
    stdio: ['ignore', log, log],
  });
  owned.push(child);
  return child;
}

async function waitReady(url, child) {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    if (child?.exitCode !== null && child?.exitCode !== undefined) {
      throw new Error(`Test service exited (${child.exitCode}). See logs in ${output}.`);
    }
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 200));
  }
  throw new Error(`Test service did not become ready: ${url}`);
}

async function scenario(name, run) {
  const started = Date.now();
  try {
    const details = await run();
    results.push({ name, status: 'pass', elapsed_ms: Date.now() - started, ...details });
    process.stdout.write(`PASS ${name}\n`);
  } catch (error) {
    results.push({ name, status: 'fail', elapsed_ms: Date.now() - started, error: String(error.stack || error) });
    process.stdout.write(`FAIL ${name}: ${error.message}\n`);
  }
}

async function json(url, init = {}) {
  const response = await fetch(base + url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init.headers },
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(`${response.status}: ${JSON.stringify(payload)}`);
  return payload;
}

async function waitRun(runId) {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    const run = await json(`/api/runs/${runId}`);
    if (['completed', 'failed', 'approval_required', 'clarification_required', 'paused'].includes(run.status)) return run;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error(`Run did not settle: ${runId}`);
}

try {
  let apiChild;
  if (!args.includes('--external-server')) {
    apiChild = launch('api', path.join(root, '.venv/bin/python'), [
      '-m', 'tests.ui.server', '--storage', storage, '--port', String(apiPort), '--frontend-root', frontendRoot,
    ], { PYTHONUNBUFFERED: '1', LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' });
  }
  await waitReady(base + '/health', apiChild);
  const manifestPath = arg('--manifest', path.join(storage, 'ui-manifest.json'));
  const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  const chrome = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  browser = await chromium.launch({ executablePath: fs.existsSync(chrome) ? chrome : undefined, headless: true, args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] });
  browserVersion = browser.version();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, permissions: ['microphone'] });
  context.setDefaultTimeout(10_000);
  const page = await context.newPage();
  page.on('pageerror', error => errors.push({ message: error.message, url: page.url() }));
  page.on('console', event => {
    if (event.type() === 'error') consoleErrors.push({ message: event.text(), url: page.url(), location: event.location() });
  });
  page.on('response', response => {
    if (response.status() >= 400) httpErrors.push({ url: response.url(), status: response.status() });
  });
  const openThread = async thread => {
    await page.goto(`${base}/workspace/?thread=${thread}`);
    await expect(page.getByLabel('Message', { exact: true })).toBeVisible();
  };

  await scenario('React source selection and ordinary conversation', async () => {
    await page.goto(base + '/workspace/');
    await page.getByRole('button', { name: 'New workspace', exact: true }).click();
    await expect(page.getByLabel('Source', { exact: true })).toBeVisible();
    await page.getByLabel('Source', { exact: true }).selectOption('ui_sales');
    await page.getByRole('button', { name: 'Open workspace', exact: true }).click();
    await page.getByLabel('Message', { exact: true }).fill('Hello');
    await page.getByRole('button', { name: 'Send', exact: true }).click();
    await expect(page.getByText('Hello. The browser test workspace is ready.', { exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(output, 'react-conversation.png'), fullPage: true });
  });

  await scenario('React saved evidence, chart and report', async () => {
    await openThread(manifest.thread_id);
    await expect(page.getByText('Monthly sales by region', { exact: true }).first()).toBeVisible();
    await expect(page.locator('.js-plotly-plot').first()).toBeVisible();
    await expect(page.getByText('Observed monthly sales use source units.', { exact: true }).first()).toBeVisible();
    await page.getByRole('tab', { name: 'Report', exact: true }).click();
    await expect(page.locator('iframe').first()).toBeVisible();
    const workspaceBrand = await page.evaluate(() => {
      const styles = getComputedStyle(document.documentElement);
      return { primary: styles.getPropertyValue('--accent').trim().toLowerCase(), background: styles.getPropertyValue('--bg').trim().toLowerCase(), text: styles.getPropertyValue('--ink').trim().toLowerCase(), font: getComputedStyle(document.body).fontFamily, headingFont: getComputedStyle(document.querySelector('h2')).fontFamily };
    });
    const reportBrand = await page.frameLocator('iframe').locator('body').evaluate(body => {
      const styles = getComputedStyle(body.ownerDocument.documentElement);
      return { primary: styles.getPropertyValue('--primary').trim().toLowerCase(), background: styles.getPropertyValue('--background').trim().toLowerCase(), text: styles.getPropertyValue('--text').trim().toLowerCase(), font: getComputedStyle(body).fontFamily, headingFont: getComputedStyle(body.querySelector('h1')).fontFamily };
    });
    expect({ ...workspaceBrand, headingFont: undefined }).toEqual({ ...reportBrand, headingFont: undefined });
    expect(workspaceBrand.headingFont).toContain('Source Sans 3');
    await page.getByRole('tab', { name: 'Data', exact: true }).click();
    await expect(page.getByRole('columnheader', { name: 'region', exact: true })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'North', exact: true }).first()).toBeVisible();
    await page.screenshot({ path: path.join(output, 'react-evidence.png'), fullPage: true });
    return { shared_report_brand: workspaceBrand };
  });

  await scenario('React ordinary and saved charts preserve declared interval meaning', async () => {
    await openThread(manifest.scenario_thread_id);
    const note = 'Scenario range. Method: Illustrative plus or minus 10 percent; no probability is assigned.';
    await expect(page.getByText(note, { exact: true }).first()).toBeVisible();
    await page.getByRole('button', { name: 'Save dashboard', exact: true }).click();
    await page.getByRole('dialog').getByRole('button', { name: 'Create dashboard', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Monthly sales scenario', exact: true })).toBeVisible();
    await expect(page.getByText(note, { exact: true }).first()).toBeVisible();
    await expect.poll(() => new URL(page.url()).searchParams.get('dashboard')).toBeTruthy();
    const board = await json(`/api/conversations/${manifest.scenario_thread_id}/dashboards/${new URL(page.url()).searchParams.get('dashboard')}`);
    expect(board.components.find(c => c.type === 'chart').notes).toContain(note);
    return { ordinary_interval_caption_visible: true, saved_dashboard_interval_caption_visible: true };
  });

  await scenario('React requested dashboard opens after its report completes', async () => {
    await page.getByRole('button', { name: 'New workspace', exact: true }).click();
    await page.getByLabel('Source', { exact: true }).selectOption('ui_sales');
    await page.getByRole('button', { name: 'Open workspace', exact: true }).click();
    await page.getByLabel('Message', { exact: true }).fill('Show monthly sales as a dashboard.');
    const sent = page.waitForResponse(r => r.url().endsWith('/messages') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Create dashboard', exact: true }).click();
    const response = await sent;
    expect(response.request().postDataJSON().dashboard).toBe(true);
    expect((await waitRun((await response.json()).run_id)).status).toBe('completed');
    await expect(page.getByRole('heading', { name: 'Monthly sales dashboard', exact: true })).toBeVisible();
    expect(new URL(page.url()).searchParams.get('dashboard')).toBeTruthy();
    await expect(page.locator('.js-plotly-plot').first()).toBeVisible();
  });

  await scenario('React required schema review before analysis', async () => {
    await openThread(manifest.upload_thread_id);
    await expect(page.getByText('review-sales.csv', { exact: false }).first()).toBeVisible();
    const confirmed = page.waitForResponse(r => r.url().includes(`/uploads/${manifest.upload_id}/confirm`) && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Confirm data and continue', exact: true }).click();
    expect((await confirmed).status()).toBe(200);
    await expect(page.getByRole('button', { name: 'Confirm data and continue', exact: true })).toHaveCount(0);
    const uploads = await json(`/api/conversations/${manifest.upload_thread_id}/uploads`);
    expect(uploads.uploads[0].confirmed).toBe(true);
    await page.screenshot({ path: path.join(output, 'react-file-review.png'), fullPage: true });
  });

  await scenario('React clarification and configured SQL review', async () => {
    await openThread(manifest.clarification_thread_id);
    await expect(page.getByText('Which declared region should the analysis cover?', { exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible();
    await page.getByLabel('Clarification answer', { exact: true }).fill('North');
    const clarified = page.waitForResponse(r => r.url().endsWith(`/api/runs/${manifest.clarification_run_id}/clarification`) && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Continue analysis', exact: true }).click();
    expect((await clarified).status()).toBe(202);
    expect((await waitRun(manifest.clarification_run_id)).status).toBe('completed');
    await openThread(manifest.review_thread_id);
    await expect(page.getByText('Review the generated SQL before it is executed.', { exact: false }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(output, 'react-sql-review.png'), fullPage: true });
    const decision = page.getByLabel('Decision', { exact: false }).first();
    await expect(decision).toHaveValue('');
    await decision.selectOption('approve');
    const reviewed = page.waitForResponse(r => r.url().endsWith(`/api/runs/${manifest.review_run_id}/decisions`) && r.request().method() === 'POST');
    await page.getByRole('button', { name: /Submit.*review|Continue with decisions/i }).click();
    expect((await reviewed).status()).toBe(202);
    expect((await waitRun(manifest.review_run_id)).status).toBe('completed');
  });

  await scenario('React Python input review and exact edited-code approval', async () => {
    await openThread(manifest.python_review_thread_id);
    await expect(page.getByRole('heading', { name: 'Python analysis', exact: true })).toBeVisible();
    await page.getByText('Bound input datasets', { exact: false }).click();
    await expect(page.getByText('4 saved rows', { exact: false }).first()).toBeVisible();
    const decision = page.getByLabel('Decision', { exact: false }).first();
    await expect(decision).toHaveValue('');
    await expect(page.getByRole('button', { name: 'Submit review', exact: true })).toBeDisabled();
    await decision.selectOption('edit');
    const editedCode = "# Exact browser-reviewed edit\nsummary = datasets['sales'].copy()\noutput_datasets = {'summary': summary}";
    await page.getByLabel('Proposed python 1', { exact: true }).fill(editedCode);
    const submitted = page.waitForResponse(r => r.url().endsWith(`/api/runs/${manifest.python_review_run_id}/decisions`) && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Submit review', exact: true }).click();
    const response = await submitted;
    expect(response.status()).toBe(202);
    expect(response.request().postDataJSON().decisions[0].edited_python).toBe(editedCode);
    expect((await waitRun(manifest.python_review_run_id)).status).toBe('completed');
    await page.screenshot({ path: path.join(output, 'react-python-reviewed.png'), fullPage: true });
    return { exact_reviewed_code_submitted: true, no_preselected_approval: true };
  });

  await scenario('React save dashboard, declare a shared filter and preserve the old view while updating', async () => {
    await openThread(manifest.thread_id);
    await page.getByRole('button', { name: 'Save dashboard', exact: true }).click();
    await page.getByRole('dialog').getByLabel('Dashboard title').fill('Sales review dashboard');
    await page.getByRole('dialog').getByRole('button', { name: 'Create dashboard', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Sales review dashboard', exact: true })).toBeVisible();
    savedDashboardId = new URL(page.url()).searchParams.get('dashboard');
    expect(savedDashboardId).toBeTruthy();
    await page.getByRole('button', { name: 'Add filter', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByLabel('Filter label', { exact: true }).fill('Sales region');
    await dialog.getByLabel('Filter meaning', { exact: true }).fill('Declared sales region. Apply the same region to the monthly chart and its table.');
    const bindings = dialog.getByLabel(/^Filter column for /);
    await expect(bindings).toHaveCount(2);
    for (const binding of await bindings.all()) await binding.selectOption('region');
    await dialog.getByRole('button', { name: 'Save filter', exact: true }).click();
    await expect(dialog).toHaveCount(0);
    const endpoint = `/api/conversations/${manifest.thread_id}/dashboards/${savedDashboardId}`;
    const before = await json(endpoint);
    expect(before.components.find(c => c.type === 'table').row_count).toBe(4);
    await page.getByLabel('Sales region', { exact: true }).selectOption({ label: 'South' });
    const applied = page.waitForResponse(r => r.url().endsWith(endpoint + '/actions') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
    const action = await (await applied).json();
    const during = await json(endpoint);
    expect(during.revision.revision_id).toBe(before.revision.revision_id);
    expect(during.components.find(c => c.type === 'table').row_count).toBe(4);
    const run = await waitRun(action.run_id);
    expect(run.status, run.error || '').toBe('completed');
    const after = await json(endpoint);
    expect(after.revision.revision_id).not.toBe(before.revision.revision_id);
    expect(after.revision.report_id).not.toBe(before.revision.report_id);
    const table = after.components.find(c => c.type === 'table');
    expect(table.row_count).toBe(2);
    expect(table.rows.every(row => row.region === 'South')).toBe(true);
    await expect(page.getByText('Applied: Sales region: South', { exact: false })).toBeVisible();
    await expect(page.getByText('Observed monthly sales use source units.', { exact: true }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Refresh data', exact: true })).toBeEnabled();
    await page.screenshot({ path: path.join(output, 'react-dashboard-filtered.png'), fullPage: true });
  });

  await scenario('React saved view, refresh, idempotency and stale-revision protection', async () => {
    expect(savedDashboardId).toBeTruthy();
    await page.getByLabel('Sales region', { exact: true }).selectOption({ label: 'North' });
    await page.getByRole('button', { name: 'Edit view', exact: true }).click();
    await page.getByLabel('Dashboard title', { exact: true }).fill('Regional sales workspace');
    await page.getByRole('button', { name: 'Save view', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'Regional sales workspace', exact: true })).toBeVisible();
    const endpoint = `/api/conversations/${manifest.thread_id}/dashboards/${savedDashboardId}`;
    const before = await json(endpoint);
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Regional sales workspace', exact: true })).toBeVisible();
    await expect(page.getByLabel('Sales region', { exact: true })).toHaveValues(['"North"']);
    await expect(page.getByText('Applied: Sales region: South', { exact: false })).toBeVisible();
    expect(Object.values(before.revision.saved_filter_values)).toEqual([['North']]);
    const refreshed = page.waitForResponse(r => r.url().endsWith(endpoint + '/actions') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Refresh data', exact: true }).click();
    const response = await refreshed;
    expect(response.status()).toBe(202);
    const action = await response.json();
    const requestBody = response.request().postDataJSON();
    const duplicate = await json(endpoint + '/actions', { method: 'POST', body: JSON.stringify(requestBody) });
    expect(duplicate.run_id).toBe(action.run_id);
    expect((await waitRun(action.run_id)).status).toBe('completed');
    const after = await json(endpoint);
    expect(after.revision.report_id).not.toBe(before.revision.report_id);
    expect(after.revision.applied_filters).toEqual(before.revision.applied_filters);
    const stale = await fetch(base + endpoint + '/view', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_revision: before.revision.revision_id, request_id: crypto.randomUUID(), title: 'Stale overwrite' }) });
    expect(stale.status).toBe(409);
    await expect(page.getByRole('button', { name: 'Refresh data', exact: true })).toBeEnabled();
    await page.screenshot({ path: path.join(output, 'react-dashboard-reopened.png'), fullPage: true });
    return { immutable_report_history: true, duplicate_action_reused_run: true, stale_revision_status: stale.status };
  });

  await scenario('React failed investigation retains the valid dashboard and evidence', async () => {
    const endpoint = `/api/conversations/${manifest.thread_id}/dashboards/${savedDashboardId}`;
    const before = await json(endpoint);
    await page.getByRole('button', { name: 'Investigate Monthly sales by region', exact: true }).click();
    await page.getByLabel('Investigation question', { exact: true }).fill('Simulate failure for the browser regression.');
    const request = page.waitForResponse(r => r.url().endsWith(endpoint + '/actions') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Start investigation', exact: true }).click();
    const action = await (await request).json();
    expect((await waitRun(action.run_id)).status).toBe('failed');
    const after = await json(endpoint);
    expect(after.revision.revision_id).toBe(before.revision.revision_id);
    expect(after.components).toEqual(before.components);
    await expect(page.getByText('Intentional browser-test failure.', { exact: false }).first()).toBeVisible();
    await page.screenshot({ path: path.join(output, 'react-dashboard-failure.png'), fullPage: true });
  });

  await scenario('React empty filter results and reset preserve explicit evidence', async () => {
    const endpoint = `/api/conversations/${manifest.thread_id}/dashboards/${savedDashboardId}`;
    await page.getByLabel('Sales region', { exact: true }).selectOption('');
    await page.getByText('Other value', { exact: true }).click();
    await page.getByLabel('Sales region custom value', { exact: true }).fill('No matching region');
    await page.getByRole('button', { name: 'Add custom Sales region', exact: true }).click();
    const submitted = page.waitForResponse(r => r.url().endsWith(endpoint + '/actions') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
    const action = await (await submitted).json();
    const run = await waitRun(action.run_id);
    expect(run.status, run.error || '').toBe('completed');
    const empty = await json(endpoint);
    expect(empty.components.find(c => c.type === 'table').row_count).toBe(0);
    expect(empty.components.find(c => c.type === 'chart').chart_id).toBeNull();
    await expect(page.getByRole('heading', { name: 'No data for this selection', exact: true })).toBeVisible();
    await page.screenshot({ path: path.join(output, 'react-dashboard-empty.png'), fullPage: true });
    await page.getByLabel('Sales region', { exact: true }).selectOption('');
    const reset = page.waitForResponse(r => r.url().endsWith(endpoint + '/actions') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Apply filters', exact: true }).click();
    expect((await waitRun((await (await reset).json()).run_id)).status).toBe('completed');
    const restored = await json(endpoint);
    expect(restored.components.find(c => c.type === 'table').row_count).toBe(4);
    expect(restored.components.find(c => c.type === 'chart').chart_id).toBeTruthy();
    await expect(page.locator('.js-plotly-plot').first()).toBeVisible();
  });

  await scenario('React narrow layout and keyboard focus', async () => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`${base}/workspace/?thread=${manifest.thread_id}&dashboard=${savedDashboardId}`);
    await expect(page.getByLabel('Sales region', { exact: true })).toBeVisible();
    await expect(page.locator('.js-plotly-plot').first()).toBeVisible();
    await expect(page.getByText('Preparing chart…', { exact: true })).toHaveCount(0);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.keyboard.press('Tab');
    expect(await page.evaluate(() => document.activeElement !== document.body)).toBe(true);
    await page.getByRole('group', { name: 'Workspace panels', exact: true }).getByRole('button', { name: 'Conversation', exact: true }).click();
    await page.getByLabel('Message', { exact: true }).focus();
    await expect(page.getByLabel('Message', { exact: true })).toBeFocused();
    await page.screenshot({ path: path.join(output, 'react-mobile.png'), fullPage: true });
    await page.setViewportSize({ width: 1440, height: 1000 });
  });

  await scenario('React dark theme and editable voice draft', async () => {
    await page.getByRole('button', { name: 'Use dark theme', exact: true }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    await expect(page.getByRole('button', { name: 'Edit view', exact: true })).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
    await page.screenshot({ path: path.join(output, 'react-dashboard-dark.png'), fullPage: true });
    await page.getByRole('button', { name: 'Use light theme', exact: true }).click();
    const before = await json(`/api/conversations/${manifest.thread_id}`);
    await page.getByLabel('Message', { exact: true }).fill('');
    await page.getByRole('button', { name: 'Record question', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Stop recording', exact: true })).toBeVisible();
    // The fake input must supply enough samples to form a real WAV recording.
    await page.waitForTimeout(500);
    const transcribed = page.waitForResponse(r => r.url().endsWith('/api/transcriptions') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Stop recording', exact: true }).click();
    expect((await transcribed).status()).toBe(200);
    await expect(page.getByLabel('Message', { exact: true })).toHaveValue('Show monthly sales for the North region.');
    const after = await json(`/api/conversations/${manifest.thread_id}`);
    expect(after.run_ids).toEqual(before.run_ids);
    await page.getByLabel('Message', { exact: true }).fill('Show monthly sales for all declared regions.');
    await expect(page.getByLabel('Message', { exact: true })).toHaveValue('Show monthly sales for all declared regions.');
    await page.screenshot({ path: path.join(output, 'react-voice-draft.png'), fullPage: true });
    return { transcription_provider_stubbed: true, pcm_wav_verified: true, draft_not_auto_submitted: true };
  });

  await scenario('React real CSV and Parquet attachment, explicit review and saved-data analysis', async () => {
    await page.getByRole('button', { name: 'New workspace', exact: true }).click();
    const uploaded = page.waitForResponse(r => r.url().includes('/api/uploads?') && r.request().method() === 'POST');
    await page.getByLabel('Attach file', { exact: true }).first().setInputFiles(manifest.input_paths.csv);
    expect((await uploaded).status()).toBe(201);
    await expect(page.getByRole('heading', { name: 'Confirm the data to analyze', exact: true })).toBeVisible();
    await expect(page.getByLabel('Message', { exact: true })).toBeDisabled();
    importedThreadId = new URL(page.url()).searchParams.get('thread');
    await page.getByLabel('Type for sales', { exact: true }).selectOption('number');
    await page.getByLabel('What does one row represent?', { exact: false }).fill('One calendar month and region.');
    const confirmed = page.waitForResponse(r => r.url().endsWith('/confirm') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Confirm data and continue', exact: true }).click();
    expect((await confirmed).status()).toBe(200);
    const uploads = await json(`/api/conversations/${importedThreadId}/uploads`);
    expect(uploads.uploads[0].review.types.sales).toBe('number');
    expect(uploads.uploads[0].review.grain).toBe('One calendar month and region.');
    await page.getByLabel('Message', { exact: true }).fill('Show monthly sales');
    const sent = page.waitForResponse(r => r.url().endsWith('/messages') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Send', exact: true }).click();
    const run = await waitRun((await (await sent).json()).run_id);
    expect(run.status, run.error || '').toBe('completed');
    const result = await json(`/api/results/${run.answer.results[0].result_id}`);
    expect(result.row_count).toBe(2);
    expect(result.executed_sql).toContain('input_rows');
    await page.getByRole('tab', { name: 'Data', exact: true }).click();
    const additional = page.waitForResponse(r => r.url().includes('/api/uploads?') && r.request().method() === 'POST');
    await page.getByLabel('Attach file', { exact: true }).first().setInputFiles(manifest.input_paths.parquet);
    expect((await additional).status()).toBe(201);
    await expect(page.getByRole('heading', { name: 'Confirm the data to analyze', exact: true })).toBeVisible();
    const additionalReview = page.waitForResponse(r => r.url().endsWith('/confirm') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Confirm data and continue', exact: true }).click();
    expect((await additionalReview).status()).toBe(200);
    const after = await json(`/api/conversations/${importedThreadId}/uploads`);
    expect(after.uploads).toHaveLength(2);
    expect(after.uploads.every(upload => upload.confirmed)).toBe(true);
    await page.screenshot({ path: path.join(output, 'react-multiple-files.png'), fullPage: true });
  });

  await scenario('React Excel selection, modal keyboard behavior and explicit table review', async () => {
    await page.getByRole('button', { name: 'New workspace', exact: true }).click();
    await page.getByLabel('Attach file', { exact: true }).first().setInputFiles(manifest.input_paths.excel);
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'browser-sales.xlsx', exact: true })).toBeVisible();
    await expect.poll(() => dialog.evaluate(el => el.contains(document.activeElement))).toBe(true);
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await page.getByLabel('Attach file', { exact: true }).first().setInputFiles(manifest.input_paths.excel);
    await expect(dialog.getByRole('heading', { name: 'browser-sales.xlsx', exact: true })).toBeVisible();
    await dialog.getByRole('combobox').selectOption('Sales');
    await dialog.getByLabel('Table range', { exact: true }).fill('A1:C5');
    const uploaded = page.waitForResponse(r => r.url().includes('/api/uploads?') && r.request().method() === 'POST');
    await dialog.getByRole('button', { name: 'Import selected table', exact: true }).click();
    expect((await uploaded).status()).toBe(201);
    await expect(page.getByRole('heading', { name: 'Confirm the data to analyze', exact: true })).toBeVisible();
    await expect.poll(() => new URL(page.url()).searchParams.get('thread')).toBeTruthy();
    const excelThread = new URL(page.url()).searchParams.get('thread');
    const confirmed = page.waitForResponse(r => r.url().endsWith('/confirm') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Confirm data and continue', exact: true }).click();
    expect((await confirmed).status()).toBe(200);
    const uploads = await json(`/api/conversations/${excelThread}/uploads`);
    expect(uploads.uploads[0].excel_selection.cell_range).toBe('A1:C5');
    expect(uploads.uploads[0].row_count).toBe(4);
    await page.screenshot({ path: path.join(output, 'react-excel-reviewed.png'), fullPage: true });
    await page.getByLabel('Workspace options', { exact: true }).click();
    await page.getByRole('button', { name: 'Delete workspace', exact: true }).click();
    await page.getByRole('button', { name: 'Delete workspace permanently', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Open workspace', exact: true })).toBeVisible();
    expect((await fetch(base + `/api/conversations/${excelThread}`)).status).toBe(404);
  });

  await scenario('React document context and artifact downloads', async () => {
    await openThread(manifest.thread_id);
    await page.getByRole('tab', { name: 'Data', exact: true }).click();
    const uploaded = page.waitForResponse(r => r.url().includes('/api/documents?') && r.request().method() === 'POST');
    await page.getByLabel('Attach file', { exact: true }).first().setInputFiles(manifest.input_paths.document);
    expect((await uploaded).status()).toBe(201);
    await expect(page.getByText('The reporting grain is one month and region.', { exact: false }).first()).toBeVisible();
    const csvDownload = page.waitForEvent('download');
    await page.getByRole('link', { name: 'CSV', exact: true }).click();
    const csv = await csvDownload;
    expect(csv.suggestedFilename()).toMatch(/\.csv$/);
    await csv.saveAs(path.join(output, 'downloaded-evidence.csv'));
    await page.getByRole('tab', { name: 'Report', exact: true }).click();
    const htmlDownload = page.waitForEvent('download');
    await page.getByRole('link', { name: 'HTML report', exact: true }).click();
    const html = await htmlDownload;
    expect(html.suggestedFilename()).toMatch(/\.html$/);
    await html.saveAs(path.join(output, 'downloaded-report.html'));
    await page.screenshot({ path: path.join(output, 'react-document-report.png'), fullPage: true });
  });

  await scenario('React ordinary follow-up carries the displayed dashboard revision', async () => {
    const endpoint = `/api/conversations/${manifest.thread_id}/dashboards/${savedDashboardId}`;
    const before = await json(endpoint);
    await page.goto(`${base}/workspace/?thread=${manifest.thread_id}&dashboard=${savedDashboardId}`);
    await page.getByRole('button', { name: 'Toggle conversation', exact: true }).click();
    await page.getByLabel('Message', { exact: true }).fill('Show monthly sales using the displayed dashboard context.');
    const sent = page.waitForResponse(r => r.url().endsWith('/messages') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Send', exact: true }).click();
    const response = await sent;
    expect(response.status()).toBe(202);
    const payload = response.request().postDataJSON();
    expect(payload.dashboard_id).toBe(savedDashboardId);
    expect(payload.dashboard_revision).toBe(before.revision.revision_id);
    expect((await waitRun((await response.json()).run_id)).status).toBe('completed');
    const unchanged = await json(endpoint);
    expect(unchanged.revision.revision_id).toBe(before.revision.revision_id);
    const history = await json(endpoint + '/revisions');
    const stale = await fetch(base + `/api/conversations/${manifest.thread_id}/messages`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message: 'Use an obsolete dashboard revision.', dashboard_id: savedDashboardId, dashboard_revision: history.revisions[0].revision_id }) });
    expect(stale.status).toBe(409);
    return { current_revision_included: true, stale_followup_status: stale.status };
  });

  await scenario('React prose during a typed dashboard action is a queued follow-up', async () => {
    const endpoint = `/api/conversations/${manifest.thread_id}/dashboards/${savedDashboardId}`;
    const before = await json(endpoint);
    await page.getByLabel('Message', { exact: true }).fill('Hello, save this as a follow-up question.');
    const refreshing = page.waitForResponse(r => r.url().endsWith(endpoint + '/actions') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Refresh data', exact: true }).click();
    const action = await (await refreshing).json();
    const corrected = page.waitForResponse(r => r.url().endsWith(`/api/runs/${action.run_id}/corrections`) && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Send correction', exact: true }).click();
    const response = await corrected;
    expect(response.status()).toBe(202);
    const followUp = await response.json();
    expect(followUp.disposition).toBe('follow_up');
    await expect(page.getByText('Saved as a follow-up. The current dashboard action keeps its declared filters.', { exact: true })).toBeVisible();
    expect((await waitRun(action.run_id)).status).toBe('completed');
    expect((await waitRun(followUp.run_id)).status).toBe('completed');
    const after = await json(endpoint);
    expect(after.revision.applied_filters).toEqual(before.revision.applied_filters);
    expect(after.revision.run_id).toBe(action.run_id);
    return { typed_action_filters_preserved: true, prose_queued_separately: true };
  });

  await scenario('React Stop and Resume retain the committed dashboard until completion', async () => {
    const endpoint = `/api/conversations/${manifest.thread_id}/dashboards/${savedDashboardId}`;
    await page.goto(`${base}/workspace/?thread=${manifest.thread_id}&dashboard=${savedDashboardId}`);
    await page.getByRole('button', { name: 'Toggle conversation', exact: true }).click();
    const before = await json(endpoint);
    const refreshing = page.waitForResponse(r => r.url().endsWith(endpoint + '/actions') && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Refresh data', exact: true }).click();
    const action = await (await refreshing).json();
    const stopped = page.waitForResponse(r => r.url().endsWith(`/api/runs/${action.run_id}/stop`) && r.request().method() === 'POST');
    await page.getByRole('button', { name: 'Stop', exact: true }).click();
    expect((await stopped).status()).toBe(200);
    expect((await waitRun(action.run_id)).status).toBe('paused');
    const paused = await json(endpoint);
    expect(paused.revision).toEqual(before.revision);
    expect(paused.components).toEqual(before.components);
    await expect(page.getByRole('button', { name: 'Resume analysis', exact: true })).toBeVisible();
    const [resumed] = await Promise.all([
      page.waitForResponse(r => r.url().endsWith(`/api/runs/${action.run_id}/resume`) && r.request().method() === 'POST'),
      page.getByRole('button', { name: 'Resume analysis', exact: true }).click(),
    ]);
    expect(resumed.status()).toBe(202);
    expect((await waitRun(action.run_id)).status).toBe('completed');
    const after = await json(endpoint);
    expect(after.revision.revision_id).not.toBe(before.revision.revision_id);
    expect(after.revision.report_id).not.toBe(before.revision.report_id);
    return { same_run_resumed: true, paused_view_preserved: true };
  });

  await scenario('React displays every saved category value from the shared dashboard', async () => {
    const endpoint = `/api/conversations/${manifest.thread_id}/dashboards/${savedDashboardId}`;
    const before = await json(endpoint);
    const filterId = before.revision.spec.filters[0].id;
    await json(endpoint + '/view', { method: 'POST', body: JSON.stringify({ expected_revision: before.revision.revision_id, request_id: crypto.randomUUID(), saved_filter_values: { [filterId]: ['North', 'South'] } }) });
    await page.goto(`${base}/workspace/?thread=${manifest.thread_id}&dashboard=${savedDashboardId}`);
    await expect(page.getByLabel('Sales region', { exact: true })).toHaveValues(['"North"', '"South"']);
    await page.getByRole('button', { name: 'Edit view', exact: true }).click();
    const savedRequest = page.waitForResponse(response => response.url().endsWith(endpoint + '/view') && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Save view', exact: true }).click();
    expect((await savedRequest).status()).toBe(200);
    const saved = await json(endpoint);
    expect(saved.revision.saved_filter_values[filterId]).toEqual(['North', 'South']);
    expect(saved.revision.applied_filters).toEqual(before.revision.applied_filters);
    await page.getByLabel('Sales region', { exact: true }).selectOption('');
    await page.getByRole('button', { name: 'Edit view', exact: true }).click();
    const resetDraft = page.waitForResponse(response => response.url().endsWith(endpoint + '/view') && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Save view', exact: true }).click();
    expect((await resetDraft).status()).toBe(200);
    await expect(page.getByRole('heading', { name: 'Edit the saved view', exact: true })).toHaveCount(0);
    return { all_shared_values_visible: true, draft_preserved_until_explicit_change: true };
  });

  if (!args.includes('--external-server')) {
    await scenario('React dashboard survives an API process restart', async () => {
      const endpoint = `/api/conversations/${manifest.thread_id}/dashboards/${savedDashboardId}`;
      const before = await json(endpoint);
      apiChild.kill('SIGTERM');
      await new Promise(resolve => {
        const timeout = setTimeout(() => { apiChild.kill('SIGKILL'); resolve(); }, 5000);
        apiChild.once('exit', () => { clearTimeout(timeout); resolve(); });
      });
      apiChild = launch('api-restarted', path.join(root, '.venv/bin/python'), [
        '-m', 'tests.ui.server', '--storage', storage, '--port', String(apiPort), '--frontend-root', frontendRoot,
      ], { PYTHONUNBUFFERED: '1', LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' });
      await waitReady(base + '/health', apiChild);
      const after = await json(endpoint);
      expect(after.revision).toEqual(before.revision);
      expect(after.components).toEqual(before.components);
      await page.goto(`${base}/workspace/?thread=${manifest.thread_id}&dashboard=${savedDashboardId}`);
      await expect(page.getByRole('heading', { name: 'Regional sales workspace', exact: true })).toBeVisible();
      await expect(page.locator('.js-plotly-plot').first()).toBeVisible();
      await page.screenshot({ path: path.join(output, 'react-after-restart.png'), fullPage: true });
    });
  }

  if (!args.includes('--skip-streamlit')) {
    await scenario('Streamlit saved evidence and shared dashboard lifecycle', async () => {
      const child = launch('streamlit', path.join(root, '.venv/bin/python'), [
        '-m', 'streamlit', 'run', 'streamlit_app.py', '--server.address=127.0.0.1',
        `--server.port=${streamlitPort}`, '--server.headless=true', '--server.runOnSave=false',
        '--browser.gatherUsageStats=false',
      ], { API_BASE_URL: base, ANALYTICS_STORAGE_DIR: storage, OPENAI_API_KEY: 'browser-test-no-provider' });
      const streamlit = `http://127.0.0.1:${streamlitPort}`;
      await waitReady(streamlit + '/_stcore/health', child);
      const st = await context.newPage();
      st.on('pageerror', error => errors.push({ message: error.message, url: st.url() }));
      st.on('console', event => {
        if (event.type() === 'error') consoleErrors.push({ message: event.text(), url: st.url(), location: event.location() });
      });
      st.on('response', response => {
        if (response.status() >= 400) httpErrors.push({ url: response.url(), status: response.status() });
      });
      await st.goto(`${streamlit}/?thread_id=${manifest.thread_id}`);
      await expect(st.getByText('The saved evidence contains monthly sales by region.', { exact: false }).first()).toBeVisible({ timeout: 20_000 });
      await expect(st.locator('[data-testid="stPlotlyChart"]').first()).toBeVisible();
      await expect(st.getByText('Report preview', { exact: true }).first()).toBeVisible();
      await expect(st.locator('[data-testid="stException"]')).toHaveCount(0);
      await st.screenshot({ path: path.join(output, 'streamlit-evidence.png'), fullPage: true });
      await st.getByText('Saved dashboards', { exact: true }).click();
      await expect(st.getByRole('heading', { name: 'Regional sales workspace', exact: true })).toBeVisible();
      await expect(st.getByRole('button', { name: 'Refresh dashboard data', exact: true })).toBeEnabled();
      await expect(st.getByText('Observed monthly sales use source units.', { exact: true }).first()).toBeVisible();
      const savedPanel = st.locator('[data-testid="stExpander"]').filter({ has: st.getByText('Saved dashboards', { exact: true }) });
      await expect(st.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0, { timeout: 20_000 });
      await st.getByRole('heading', { name: 'Regional sales workspace', exact: true }).scrollIntoViewIfNeeded();
      await st.screenshot({ path: path.join(output, 'streamlit-dashboard.png'), fullPage: false });
      const endpoint = `/api/conversations/${manifest.thread_id}/dashboards/${savedDashboardId}`;
      const before = await json(endpoint);
      await st.getByRole('combobox', { name: 'Sales region', exact: true }).click();
      await st.getByRole('option', { name: 'North', exact: true }).click();
      await st.getByRole('button', { name: 'Apply filters', exact: true }).click();
      const during = await json(endpoint);
      expect(during.revision.revision_id).toBe(before.revision.revision_id);
      expect(during.components).toEqual(before.components);
      await expect.poll(async () => (await json(endpoint)).revision.revision_id, { timeout: 15_000 }).not.toBe(before.revision.revision_id);
      const filtered = await json(endpoint);
      expect(filtered.components.find(c => c.type === 'table').row_count).toBe(2);
      expect(filtered.components.find(c => c.type === 'table').rows.every(row => row.region === 'North')).toBe(true);
      await expect(st.getByRole('button', { name: 'Refresh dashboard data', exact: true })).toBeEnabled({ timeout: 15_000 });
      await st.getByRole('button', { name: 'Refresh dashboard data', exact: true }).click();
      await expect.poll(async () => (await json(endpoint)).revision.revision_id, { timeout: 15_000 }).not.toBe(filtered.revision.revision_id);
      const refreshed = await json(endpoint);
      expect(refreshed.revision.applied_filters).toEqual(filtered.revision.applied_filters);
      expect(refreshed.revision.report_id).not.toBe(filtered.revision.report_id);
      await expect(st.getByRole('button', { name: 'Refresh dashboard data', exact: true })).toBeEnabled({ timeout: 15_000 });
      // A Streamlit rerun can retain the previous revision's form while drawing
      // the new one. Wait for the saved version and edit its nonstale widget.
      await expect(st.getByText(`Version ${refreshed.revision.version} · Saved ${refreshed.revision.created_at} · Source completeness is unknown.`, { exact: true })).toBeVisible();
      await expect(st.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0, { timeout: 20_000 });
      const titleInput = st.locator('[data-testid="stElementContainer"][data-stale="false"]').getByRole('textbox', { name: 'Dashboard title', exact: true });
      const titleForm = st.locator('[data-testid="stForm"]').filter({ has: titleInput });
      await expect(titleForm).toBeVisible();
      await titleForm.getByRole('textbox', { name: 'Dashboard title', exact: true }).fill('Streamlit regional sales');
      await titleForm.getByRole('button', { name: 'Save view', exact: true }).click();
      await expect(st.getByRole('heading', { name: 'Streamlit regional sales', exact: true })).toBeVisible();
      await st.reload();
      await st.getByText('Saved dashboards', { exact: true }).click();
      await expect(st.getByRole('heading', { name: 'Streamlit regional sales', exact: true })).toBeVisible();
      await expect(st.locator('[data-testid="stException"]')).toHaveCount(0);
      await expect(st.getByRole('button', { name: 'Stop', exact: true })).toHaveCount(0, { timeout: 20_000 });
      await st.getByRole('heading', { name: 'Streamlit regional sales', exact: true }).scrollIntoViewIfNeeded();
      await st.screenshot({ path: path.join(output, 'streamlit-dashboard-reopened.png'), fullPage: false });
      await savedPanel.locator('[data-testid="stPlotlyChart"]').first().evaluate(element => element.scrollIntoView({ block: 'center', behavior: 'instant' }));
      await st.mouse.move(10, 10);
      await st.screenshot({ path: path.join(output, 'streamlit-dashboard-chart.png'), fullPage: false });
      const beforeSave = await json(`/api/conversations/${manifest.thread_id}/dashboards`);
      await st.getByRole('button', { name: 'Save latest report as dashboard', exact: true }).click();
      await expect.poll(async () => (await json(`/api/conversations/${manifest.thread_id}/dashboards`)).dashboards.length).toBe(beforeSave.dashboards.length + 1);
      await expect(st.getByRole('heading', { name: 'Monthly sales evidence', exact: true })).toBeVisible();
      await expect(st.locator('[data-testid="stException"]')).toHaveCount(0);
      await st.goto(`${streamlit}/?thread_id=${manifest.scenario_thread_id}`);
      await st.getByText('Saved dashboards', { exact: true }).click();
      await expect(st.getByText('Scenario range. Method: Illustrative plus or minus 10 percent; no probability is assigned.', { exact: true }).first()).toBeVisible();
      await st.close();
      return { native_dashboard_rendered: true, explicit_filter_applied: true, old_view_preserved: true, refreshed_report_saved: true, saved_view_reopened: true, completed_report_saved_as_dashboard: true };
    });
  }
} catch (error) {
  results.push({ name: 'Test setup', status: 'fail', error: String(error.stack || error) });
} finally {
  await browser?.close();
  for (const child of owned.reverse()) {
    if (child.exitCode === null) {
      child.kill('SIGTERM');
      await new Promise(resolve => {
        const timer = setTimeout(() => { child.kill('SIGKILL'); resolve(); }, 2000);
        child.once('exit', () => { clearTimeout(timer); resolve(); });
      });
    }
  }
  const receipt = { tested_at: new Date().toISOString(), base_url: base, real_api: true, model_provider_calls: 0, browser_version: browserVersion, viewports: [{ width: 1440, height: 1000 }, { width: 390, height: 844 }], frontend_assets: fs.readdirSync(path.join(frontendRoot, 'dist/assets')), scenario_counts: { total: results.length, passed: results.filter(item => item.status === 'pass').length, failed: results.filter(item => item.status === 'fail').length }, scenarios: results, browser_errors: errors, console_errors: consoleErrors, http_errors: httpErrors, status: results.length && results.every(item => item.status === 'pass') && !errors.length && !consoleErrors.length && !httpErrors.length ? 'pass' : 'fail' };
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
  process.stdout.write(JSON.stringify(receipt, null, 2) + '\n');
  process.exitCode = receipt.status === 'pass' ? 0 : 1;
}
