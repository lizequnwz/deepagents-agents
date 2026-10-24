/** Build an isolated frontend snapshot without replacing the running product. */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const args = process.argv.slice(2);
const output = path.resolve(args.includes('--output') ? args[args.indexOf('--output') + 1] : path.join(root, 'frontend/test-results/staged'));
const frontend = path.join(output, 'frontend');
if (fs.existsSync(frontend)) throw new Error(`Choose a fresh staging output; ${frontend} already exists.`);
fs.mkdirSync(output, { recursive: true });
fs.cpSync(path.join(root, 'frontend'), frontend, {
  recursive: true,
  filter: source => !['node_modules', 'dist', 'test-results', 'playwright-report'].includes(path.relative(path.join(root, 'frontend'), source).split(path.sep)[0]) && !source.endsWith('.tsbuildinfo'),
});
fs.symlinkSync(path.join(root, 'frontend/node_modules'), path.join(frontend, 'node_modules'), 'dir');
const log = fs.openSync(path.join(output, 'build.log'), 'w');
const child = spawn('npm', ['--prefix', frontend, 'run', 'build'], { cwd: root, stdio: ['ignore', log, log] });
const exitCode = await new Promise(resolve => child.once('exit', resolve));
if (exitCode !== 0) throw new Error(`Isolated build failed (${exitCode}); inspect ${path.join(output, 'build.log')}.`);
process.stdout.write(JSON.stringify({ frontend_root: frontend, assets: fs.readdirSync(path.join(frontend, 'dist/assets')) }, null, 2) + '\n');
