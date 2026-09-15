import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createRequire } from 'node:module';
import { chromium } from '/Users/charlie/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright-core/index.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const { createCanvas, loadImage } = require('/Users/charlie/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@napi-rs/canvas');
const browser = await chromium.launch({
  executablePath: '/Users/charlie/Library/Caches/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-mac-arm64/chrome-headless-shell',
  headless: true,
});

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce', offline: true });
  await page.goto(pathToFileURL(path.join(here, '../index.html')).href);
  const ids = await page.locator('.scene').evaluateAll(elements => elements.map(element => element.id));
  const canvas = createCanvas(1200, 4 * 470);
  const context = canvas.getContext('2d');
  context.fillStyle = '#b9bdc5';
  context.fillRect(0, 0, canvas.width, canvas.height);

  for (const [index, id] of ids.entries()) {
    const imagePath = path.join(here, `scene-${String(index + 1).padStart(2, '0')}.png`);
    // Hide global chrome only for unobstructed content inspection. Separate viewport
    // screenshots and browser tests cover the actual navigation and focus behavior.
    await page.locator('#' + id).screenshot({
      path: imagePath,
      style: '.topbar,.status,.skip{visibility:hidden!important}.walk-map{position:static!important}',
    });
    const image = await loadImage(imagePath);
    const scale = Math.min(280 / image.width, 425 / image.height);
    const x = (index % 4) * 300 + 10;
    const y = Math.floor(index / 4) * 470 + 10;
    context.drawImage(image, x, y, image.width * scale, image.height * scale);
    context.fillStyle = '#141820';
    context.font = '13px sans-serif';
    context.fillText(`${index + 1}. ${id}`, x, y + 445);
  }
  fs.writeFileSync(path.join(here, 'scene-contact-sheet.png'), canvas.toBuffer('image/png'));
} finally {
  await browser.close();
}
