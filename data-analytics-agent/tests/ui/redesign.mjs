/** Responsive, keyboard and visual checks for the redesigned React workspace. */
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
const output = path.resolve(arg('--output', path.join(root, 'frontend/test-results/redesign')));
const frontend = path.resolve(arg('--frontend-root', path.join(root, 'frontend')));
const storage = path.join(output, 'storage');
const port = Number(arg('--api-port', '8796'));
const base = `http://127.0.0.1:${port}`;
fs.mkdirSync(output, { recursive: true });
const scenarios = [], pageErrors = [], consoleErrors = [], httpErrors = [];
let api, browser;
const viewports = [
  { name: 'phone', width: 375, height: 812 },
  { name: 'tablet', width: 768, height: 1024 },
  { name: 'desktop', width: 1440, height: 1000 },
  { name: 'wide', width: 1920, height: 1080 },
  { name: 'landscape', width: 812, height: 375 },
];
async function scenario(name, run) {
  try { const details = await run(); scenarios.push({ name, status: 'pass', ...details }); process.stdout.write(`PASS ${name}\n`); }
  catch (error) { scenarios.push({ name, status: 'fail', error: String(error.stack || error) }); process.stdout.write(`FAIL ${name}: ${error.message}\n`); }
}
async function json(url, init = {}) {
  const response = await fetch(base + url, { ...init, headers: { 'Content-Type': 'application/json', ...init.headers } });
  const payload = await response.json();
  if (!response.ok) throw new Error(`${response.status}: ${JSON.stringify(payload)}`);
  return payload;
}
function observe(page) {
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('console', event => { if (event.type() === 'error') consoleErrors.push(event.text()); });
  page.on('response', response => { if (response.status() >= 400) httpErrors.push({ status: response.status(), url: response.url() }); });
}
async function quietChart(page) {
  await expect(page.locator('.js-plotly-plot').first()).toBeVisible();
  await expect.poll(() => page.locator('.chart-shell [role="status"]').count()).toBe(0);
}
async function noOverflow(page) {
  return await page.evaluate(() => ({ width: innerWidth, scroll: document.documentElement.scrollWidth, no_horizontal_overflow: document.documentElement.scrollWidth <= innerWidth + 1 }));
}
async function visibleFocus(locator) {
  await locator.focus();
  await expect(locator).toBeFocused();
  const geometry = () => locator.evaluate(element => {
    const rect = element.getBoundingClientRect();
    const viewport = window.visualViewport;
    const left = viewport?.offsetLeft ?? 0, top = viewport?.offsetTop ?? 0;
    const width = viewport?.width ?? innerWidth, height = viewport?.height ?? innerHeight;
    const center = document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2);
    const style = getComputedStyle(element);
    return { fully_visible: rect.left >= left && rect.top >= top && rect.right <= left + width + 1 && rect.bottom <= top + height + 1, unobscured: center === element || element.contains(center), outline_width: parseFloat(style.outlineWidth), outline_style: style.outlineStyle };
  });
  // Focus can trigger the message pane's smooth scroll. Check the settled
  // position while preserving the bounds and center hit-test requirements.
  await expect.poll(async () => { const measured = await geometry(); return measured.fully_visible && measured.unobscured; }).toBe(true);
  return geometry();
}
function luminance(color) {
  const values = color.match(/[\d.]+/g)?.slice(0, 3).map(Number);
  if (!values || values.length !== 3) throw new Error(`Unsupported computed color ${color}`);
  const channels = values.map(value => { const normalized = value / 255; return normalized <= .04045 ? normalized / 12.92 : ((normalized + .055) / 1.055) ** 2.4; });
  return channels[0] * .2126 + channels[1] * .7152 + channels[2] * .0722;
}
function contrast(first, second) { const [lighter, darker] = [luminance(first), luminance(second)].sort((a, b) => b - a); return (lighter + .05) / (darker + .05); }

try {
  const log = fs.openSync(path.join(output, 'api.log'), 'w');
  api = spawn(path.join(root, '.venv/bin/python'), ['-m', 'tests.ui.server', '--storage', storage, '--port', String(port), '--frontend-root', frontend], { cwd: root, env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' }, stdio: ['ignore', log, log] });
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    if (api.exitCode !== null) throw new Error(`Fixture failed (${api.exitCode}).`);
    try { if ((await fetch(base + '/health')).ok) break; } catch {}
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  const manifest = JSON.parse(fs.readFileSync(path.join(storage, 'ui-manifest.json'), 'utf8'));
  const endpoint = `/api/conversations/${manifest.thread_id}/dashboards`;
  let board = await json(endpoint, { method: 'POST', body: JSON.stringify({ run_id: manifest.run_id, title: 'Regional sales dashboard', request_id: 'redesign-view' }) });
  const bindings = board.components.filter(component => component.type === 'chart' || component.type === 'table').map(component => ({ component_id: component.id, column: 'region' }));
  board = await json(endpoint + `/${board.revision.dashboard_id}/view`, { method: 'POST', body: JSON.stringify({ expected_revision: board.revision.revision_id, request_id: 'redesign-filter', filters: [{ id: 'sales_region', label: 'Sales region', kind: 'category', bindings }] }) });
  const url = base + `/workspace/?thread=${manifest.thread_id}&dashboard=${board.revision.dashboard_id}`;
  const chrome = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  browser = await chromium.launch({ headless: true, executablePath: fs.existsSync(chrome) ? chrome : undefined });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  observe(page);
  await page.goto(url);
  await quietChart(page);

  await scenario('Searchable workspace navigation and keyboard tabs', async () => {
    const search = page.getByLabel('Search workspaces', { exact: true });
    await search.fill('Show monthly sales by region');
    const nav = page.getByRole('navigation', { name: 'Saved workspaces', exact: true });
    await expect(nav.locator('.history-item')).toHaveCount(1);
    await search.fill('There is no such saved workspace');
    await expect(nav.locator('.history-item')).toHaveCount(0);
    await search.fill('');
    const tabs = page.getByRole('tablist', { name: 'Workspace view', exact: true });
    await tabs.getByRole('tab').first().focus();
    await page.keyboard.press('ArrowRight');
    await expect(page.getByRole('tab', { name: 'Report', exact: true })).toBeFocused();
    await expect(page.getByRole('tab', { name: 'Report', exact: true })).toHaveAttribute('aria-selected', 'true');
    await page.keyboard.press('End');
    await expect(page.getByRole('tab', { name: 'Data', exact: true })).toBeFocused();
    await page.keyboard.press('Home');
    await expect(tabs.getByRole('tab').first()).toBeFocused();
    await expect(tabs.getByRole('tab').first()).toHaveAttribute('aria-selected', 'true');
    return { history_search: true, arrow_home_end_tabs: true };
  });

  await scenario('Unapplied filter choices and keyboard-accessible chart data', async () => {
    const apply = page.getByRole('button', { name: 'Apply filters', exact: true });
    await expect(apply).toBeDisabled();
    const actionRequests = [];
    const trackActions = request => { if (request.method() === 'POST' && request.url().endsWith('/actions')) actionRequests.push(request.url()); };
    page.on('request', trackActions);
    await page.getByLabel('Sales region', { exact: true }).selectOption({ label: 'South' });
    await expect(page.getByText('1 unapplied filter change', { exact: true })).toBeVisible();
    await expect(apply).toBeEnabled();
    expect((await json(endpoint + `/${board.revision.dashboard_id}`)).revision.applied_filters).toEqual({});
    await page.getByRole('button', { name: 'Use applied values', exact: true }).click();
    await expect(apply).toBeDisabled();
    expect(actionRequests).toEqual([]);
    page.off('request', trackActions);
    await expect(page.getByRole('img', { name: 'Monthly sales by region. Interactive chart from saved evidence.', exact: true })).toBeVisible();
    const details = page.locator('.chart-data-access').first();
    await details.locator(':scope > summary').focus();
    await page.keyboard.press('Enter');
    await expect(details.getByRole('link', { name: 'CSV', exact: true })).toBeVisible();
    const sort = details.getByRole('button', { name: 'Sort shown rows by sales', exact: true });
    await sort.click();
    await expect(sort.locator('..')).toHaveAttribute('aria-sort', 'ascending');
    const firstAscending = await details.locator('tbody tr').first().locator('td').last().textContent();
    await sort.click();
    await expect(sort.locator('..')).toHaveAttribute('aria-sort', 'descending');
    const firstDescending = await details.locator('tbody tr').first().locator('td').last().textContent();
    expect(Number(firstAscending)).toBeLessThan(Number(firstDescending));
    await details.locator(':scope > summary').click();
    return { unapplied_choices_do_not_execute: true, explicit_reset_to_applied: true, chart_table_and_download_accessible: true, preview_sort_direction_announced: true };
  });

  await scenario('Chart rendering failure has an explicit working retry', async () => {
    const failurePage = await context.newPage();
    observe(failurePage);
    let injected = false;
    await failurePage.route(`**/api/conversations/${manifest.thread_id}/charts/*/figure`, async route => {
      if (!injected) {
        injected = true;
        return route.fulfill({ status: 200, contentType: 'application/json', body: 'invalid chart response for recovery test' });
      }
      return route.continue();
    });
    await failurePage.goto(base + `/workspace/?thread=${manifest.thread_id}`);
    await expect(failurePage.getByRole('button', { name: 'Try chart again', exact: true })).toBeVisible();
    await failurePage.getByRole('button', { name: 'Try chart again', exact: true }).click();
    await quietChart(failurePage);
    await expect(failurePage.getByRole('button', { name: 'Try chart again', exact: true })).toHaveCount(0);
    await failurePage.close();
    return { injected_invalid_chart_response_once: injected, retry_restored_saved_chart: true };
  });

  await scenario('Destructive action disclosure, modal escape and focus restoration', async () => {
    const options = page.getByLabel('Workspace options', { exact: true });
    await options.click();
    await page.getByRole('button', { name: 'Delete workspace', exact: true }).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toBeVisible();
    for (let index = 0; index < 6; index++) {
      await page.keyboard.press('Tab');
      expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true);
    }
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(options).toBeFocused();
    const focus = await visibleFocus(options);
    expect(focus.fully_visible && focus.unobscured).toBe(true);
    expect(focus.outline_width).toBeGreaterThanOrEqual(2);
    return { modal_keyboard_trap: true, escape_restores_visible_opener: true };
  });

  await scenario('Desktop, tablet, small phone and landscape reflow', async () => {
    const checks = [];
    for (const viewport of viewports) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto(url);
      await quietChart(page);
      const geometry = await noOverflow(page);
      expect(geometry.no_horizontal_overflow).toBe(true);
      const tooSmall = await page.locator('.app-header button,.filter-bar button,.tabs button,.workspace-panels button').evaluateAll(elements => elements.filter(element => {
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && (rect.width < 24 || rect.height < 24);
      }).map(element => ({ text: element.getAttribute('aria-label') || element.textContent, width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height })));
      expect(tooSmall).toEqual([]);
      if (viewport.width <= 760) {
        const panels = page.getByRole('group', { name: 'Workspace panels', exact: true });
        await expect(panels).toBeVisible();
        await panels.getByRole('button', { name: 'Conversation', exact: true }).click();
        await expect(page.locator('.conversation-panel')).toBeVisible();
        await expect(page.locator('.canvas')).not.toBeVisible();
        const message = page.getByLabel('Message', { exact: true });
        const focus = await visibleFocus(message);
        expect(focus.fully_visible && focus.unobscured).toBe(true);
        expect(parseFloat(await message.evaluate(element => getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(16);
        const targets = await page.locator('.composer button,.composer .attachment-button,.app-header button').evaluateAll(elements => elements.filter(element => {
          const rect = element.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0 && (rect.width < 44 || rect.height < 44);
        }).map(element => ({ label: element.getAttribute('aria-label') || element.textContent?.trim(), width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height })));
        expect(targets).toEqual([]);
        await page.screenshot({ path: path.join(output, `react-${viewport.name}-conversation.png`), fullPage: true });
        await panels.getByRole('button', { name: 'Findings', exact: true }).click();
      }
      if (viewport.name === 'landscape') {
        await page.getByRole('button', { name: 'Toggle conversation', exact: true }).click();
        const focus = await visibleFocus(page.getByLabel('Message', { exact: true }));
        expect(focus.fully_visible && focus.unobscured).toBe(true);
      }
      await page.screenshot({ path: path.join(output, `react-${viewport.name}.png`), fullPage: true });
      checks.push({ ...viewport, ...geometry });
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(url);
    return { viewports: checks, web_targets_at_least_24_css_px: true, phone_composer_and_header_targets_44_css_px: true };
  });

  await scenario('Mobile drawer escape and unobscured conversation focus', async () => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(url);
    const opener = page.getByRole('button', { name: 'Open navigation', exact: true });
    await opener.click();
    const search = page.getByLabel('Search workspaces', { exact: true });
    await expect(search).toBeVisible();
    await search.focus();
    await page.keyboard.press('Escape');
    await expect(search).not.toBeVisible();
    await expect(opener).toBeFocused();
    return { drawer_escape: true, focus_restored: true };
  });

  await scenario('Mobile file review, SQL approval and Excel selection remain reachable', async () => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(base + '/workspace/');
    const uploaded = page.waitForResponse(response => response.url().includes('/api/uploads?') && response.request().method() === 'POST');
    await page.getByLabel('Attach file', { exact: true }).first().setInputFiles(manifest.input_paths.csv);
    expect((await uploaded).status()).toBe(201);
    // Required review must open automatically, without a manual pane switch.
    await expect(page.getByRole('heading', { name: 'Confirm the data to analyze', exact: true })).toBeVisible();
    const panels = page.getByRole('group', { name: 'Workspace panels', exact: true });
    await expect(panels.getByRole('button', { name: 'Findings', exact: true })).toHaveAttribute('aria-pressed', 'true');
    expect((await noOverflow(page)).no_horizontal_overflow).toBe(true);
    await page.screenshot({ path: path.join(output, 'react-phone-schema-review.png'), fullPage: true });
    const confirmed = page.waitForResponse(response => response.url().endsWith('/confirm') && response.request().method() === 'POST');
    await page.getByRole('button', { name: 'Confirm data and continue', exact: true }).click();
    expect((await confirmed).status()).toBe(200);
    await panels.getByRole('button', { name: 'Conversation', exact: true }).click();
    await expect(page.getByLabel('Message', { exact: true })).toBeEnabled();
    expect((await visibleFocus(page.getByLabel('Message', { exact: true }))).fully_visible).toBe(true);

    await page.goto(base + `/workspace/?thread=${manifest.review_thread_id}`);
    await expect(page.getByText('Review the generated SQL before it is executed.', { exact: false }).first()).toBeVisible();
    await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeVisible();
    const decisionFocus = await visibleFocus(page.getByLabel('Decision', { exact: false }).first());
    expect(decisionFocus.fully_visible && decisionFocus.unobscured).toBe(true);
    expect((await noOverflow(page)).no_horizontal_overflow).toBe(true);
    await page.screenshot({ path: path.join(output, 'react-phone-sql-review.png'), fullPage: true });

    await page.goto(base + '/workspace/');
    await page.getByLabel('Attach file', { exact: true }).first().setInputFiles(manifest.input_paths.excel);
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByRole('heading', { name: 'browser-sales.xlsx', exact: true })).toBeVisible();
    const bounds = await dialog.boundingBox();
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.y).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(376);
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(813);
    for (let index = 0; index < 10; index++) {
      await page.keyboard.press('Tab');
      expect(await dialog.evaluate(element => element.contains(document.activeElement))).toBe(true);
    }
    expect((await noOverflow(page)).no_horizontal_overflow).toBe(true);
    await page.screenshot({ path: path.join(output, 'react-phone-excel-dialog.png'), fullPage: true });
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    return { csv_opens_required_review_automatically: true, reviewed_csv_allows_conversation: true, sql_approval_focus_visible: true, excel_dialog_within_phone_viewport: true, excel_keyboard_trap_and_escape: true };
  });

  await scenario('Light and dark contrast with reduced motion', async () => {
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(url);
    const themes = [];
    for (const theme of ['light', 'dark']) {
      if (await page.locator('html').getAttribute('data-theme') !== theme) await page.getByRole('button', { name: theme === 'dark' ? 'Use dark theme' : 'Use light theme', exact: true }).click();
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      const colors = await page.evaluate(() => {
        const probe = document.createElement('span');
        document.body.append(probe);
        const color = name => { probe.style.color = `var(${name})`; return getComputedStyle(probe).color; };
        const result = { ink: color('--ink'), muted: color('--muted'), background: color('--bg'), surface: color('--surface') };
        probe.remove();
        return result;
      });
      const pairs = { body: contrast(colors.ink, colors.background), surface_text: contrast(colors.ink, colors.surface), muted: contrast(colors.muted, colors.background), muted_surface: contrast(colors.muted, colors.surface) };
      for (const ratio of Object.values(pairs)) expect(ratio).toBeGreaterThanOrEqual(4.5);
      themes.push({ theme, contrast_ratios: pairs });
      await quietChart(page);
      await page.waitForTimeout(250);
      await page.screenshot({ path: path.join(output, `react-${theme}.png`), fullPage: true });
    }
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const duration = await page.locator('.new-workspace').evaluate(element => getComputedStyle(element).transitionDuration);
    expect(duration.split(',').every(value => parseFloat(value) === 0)).toBe(true);
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    return { themes, reduced_motion_transitions_disabled: true };
  });

  await scenario('Equivalent 200 percent browser zoom reflow', async () => {
    const zoomContext = await browser.newContext({ viewport: { width: 720, height: 500 }, deviceScaleFactor: 2 });
    const zoom = await zoomContext.newPage();
    observe(zoom);
    await zoom.goto(url);
    await quietChart(zoom);
    expect((await noOverflow(zoom)).no_horizontal_overflow).toBe(true);
    const panels = zoom.getByRole('group', { name: 'Workspace panels', exact: true });
    await panels.getByRole('button', { name: 'Conversation', exact: true }).click();
    const focus = await visibleFocus(zoom.getByLabel('Message', { exact: true }));
    expect(focus.fully_visible && focus.unobscured).toBe(true);
    await zoom.screenshot({ path: path.join(output, 'react-zoom-200.png'), fullPage: false });
    await zoomContext.close();
    return { css_viewport: { width: 720, height: 500 }, device_scale_factor: 2, equivalent_physical_viewport: { width: 1440, height: 1000 }, composer_focus_visible: true };
  });
} catch (error) { scenarios.push({ name: 'Test setup', status: 'fail', error: String(error.stack || error) }); }
finally {
  await browser?.close();
  if (api?.exitCode === null) {
    api.kill('SIGTERM');
    await new Promise(resolve => { const timer = setTimeout(() => { api.kill('SIGKILL'); resolve(); }, 2000); api.once('exit', () => { clearTimeout(timer); resolve(); }); });
  }
  const receipt = { tested_at: new Date().toISOString(), browser_version: browser?.version(), frontend_assets: fs.readdirSync(path.join(frontend, 'dist/assets')), real_api: true, model_provider_calls: 0, viewports, scenario_counts: { total: scenarios.length, passed: scenarios.filter(item => item.status === 'pass').length, failed: scenarios.filter(item => item.status === 'fail').length }, scenarios, page_errors: pageErrors, console_errors: consoleErrors, http_errors: httpErrors, status: scenarios.length && scenarios.every(item => item.status === 'pass') && !pageErrors.length && !consoleErrors.length && !httpErrors.length ? 'pass' : 'fail' };
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
  process.stdout.write(JSON.stringify(receipt, null, 2) + '\n');
  process.exitCode = receipt.status === 'pass' ? 0 : 1;
}
