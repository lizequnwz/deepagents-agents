/** Keep an app open across two isolated builds; the user's build is never changed. */
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
const output = path.resolve(arg('--output', path.join(root, 'frontend/test-results/deployment')));
fs.mkdirSync(output, { recursive: true });
const work = fs.mkdtempSync(path.join(output, 'run-'));
const stagedFrontend = path.join(work, 'frontend');
const storage = path.join(work, 'storage');
const port = Number(arg('--api-port', '8794'));
const base = `http://127.0.0.1:${port}`;
const owned = [];
const pageErrors = [], consoleErrors = [], httpErrors = [], scripts = [];
let browser;
let receipt = { tested_at: new Date().toISOString(), status: 'fail' };

function launch(label, command, commandArgs) {
  const log = fs.openSync(path.join(output, label + '.log'), 'w');
  const child = spawn(command, commandArgs, { cwd: root, env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' }, stdio: ['ignore', log, log] });
  owned.push(child);
  return child;
}
async function build(label) {
  const child = launch(label, 'npm', ['--prefix', stagedFrontend, 'run', 'build']);
  const code = await new Promise(resolve => child.once('exit', resolve));
  if (code !== 0) throw new Error(`${label} failed (${code}); inspect ${label}.log.`);
  const html = fs.readFileSync(path.join(stagedFrontend, 'dist/index.html'), 'utf8');
  const entry = html.match(/<script[^>]+src="([^"]+)"/)[1];
  return { entry, assets: fs.readdirSync(path.join(stagedFrontend, 'dist/assets')) };
}
async function ready(child) {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`Fixture exited (${child.exitCode}).`);
    try { if ((await fetch(base + '/health')).ok) return; } catch {}
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  throw new Error('Fixture did not start.');
}

try {
  fs.cpSync(path.join(root, 'frontend'), stagedFrontend, {
    recursive: true,
    filter: source => !['node_modules', 'dist', 'test-results'].includes(path.relative(path.join(root, 'frontend'), source).split(path.sep)[0]) && !source.endsWith('.tsbuildinfo'),
  });
  fs.symlinkSync(path.join(root, 'frontend/node_modules'), path.join(stagedFrontend, 'node_modules'), 'dir');
  const before = await build('build-a');
  const api = launch('api', path.join(root, '.venv/bin/python'), ['-m', 'tests.ui.server', '--storage', storage, '--port', String(port), '--frontend-root', stagedFrontend]);
  await ready(api);
  const manifest = JSON.parse(fs.readFileSync(path.join(storage, 'ui-manifest.json'), 'utf8'));
  const chrome = process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
  browser = await chromium.launch({ executablePath: fs.existsSync(chrome) ? chrome : undefined, headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('console', event => { if (event.type() === 'error') consoleErrors.push({ message: event.text(), location: event.location() }); });
  page.on('response', response => { if (response.status() >= 400) httpErrors.push({ url: response.url(), status: response.status() }); });
  page.on('request', request => { if (request.resourceType() === 'script') scripts.push(request.url()); });
  await page.goto(base + '/workspace/');
  await expect(page.getByRole('button', { name: 'Open workspace', exact: true })).toBeVisible();
  await expect(page.locator('.js-plotly-plot')).toHaveCount(0);
  const scriptsBeforeBuild = scripts.length;

  // Change only the isolated copy. A second build removes the old hashed entry.
  fs.appendFileSync(path.join(stagedFrontend, 'src/main.tsx'), '\ndocument.documentElement.dataset.deploymentCheck = "second";\n');
  const after = await build('build-b');
  expect(after.entry).not.toBe(before.entry);
  const oldEntry = path.join(stagedFrontend, 'dist', before.entry.replace(/^\/workspace\//, ''));
  expect(fs.existsSync(oldEntry)).toBe(false);
  await page.getByRole('navigation', { name: 'Saved workspaces', exact: true }).getByRole('button', { name: 'Show monthly sales by region', exact: true }).click();
  await expect.poll(() => new URL(page.url()).searchParams.get('thread')).toBe(manifest.thread_id);
  await expect(page.locator('.js-plotly-plot').first()).toBeVisible();
  await expect(page.getByText('Preparing chart…', { exact: true })).toHaveCount(0);
  expect(scripts.length).toBe(scriptsBeforeBuild);
  const firstChartScripts = scripts.slice(scriptsBeforeBuild);
  await page.screenshot({ path: path.join(output, 'open-tab-after-rebuild.png'), fullPage: true });

  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-deployment-check', 'second');
  await expect(page.locator('.js-plotly-plot').first()).toBeVisible();
  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(httpErrors).toEqual([]);
  receipt = { ...receipt, status: 'pass', browser_version: browser.version(), viewport: { width: 1440, height: 1000 }, build_a: before, build_b: after, old_hashed_entry_removed: true, app_open_without_chart_before_rebuild: true, first_chart_rendered_after_rebuild: true, new_script_requests_for_first_chart: firstChartScripts, reload_uses_new_build: true, model_provider_calls: 0 };
} catch (error) {
  receipt.error = String(error.stack || error);
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
  Object.assign(receipt, { page_errors: pageErrors, console_errors: consoleErrors, http_errors: httpErrors });
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
  process.stdout.write(JSON.stringify(receipt, null, 2) + '\n');
  process.exitCode = receipt.status === 'pass' ? 0 : 1;
}
