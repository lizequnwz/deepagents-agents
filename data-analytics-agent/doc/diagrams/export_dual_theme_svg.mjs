#!/usr/bin/env node

/**
 * Reproducibly export the inline Archify SVG from generated HTML.
 *
 * Archify's browser export menu performs the same transformation. This small
 * repository-local helper keeps Markdown SVG assets reproducible in headless
 * environments while retaining the generated HTML as the interactive source.
 */

import { readFile, writeFile } from "node:fs/promises";
import { basename } from "node:path";

function capture(source, pattern, label) {
  const match = source.match(pattern);
  if (!match) {
    throw new Error(`Could not find ${label}.`);
  }
  return match[1];
}

async function exportSvg(inputPath, outputPath) {
  const html = await readFile(inputPath, "utf8");
  const css = capture(html, /<style>([\s\S]*?)<\/style>/, "Archify CSS");
  const darkVariables = capture(
    css,
    /:root,\s*\[data-theme="dark"\]\s*\{([\s\S]*?)\n\s*\}/,
    "dark theme variables",
  );
  const lightVariables = capture(
    css,
    /\[data-theme="light"\]\s*\{([\s\S]*?)\n\s*\}/,
    "light theme variables",
  );
  let svg = capture(
    html,
    /(<svg\b[\s\S]*?<\/svg>)/,
    "rendered diagram SVG",
  );
  const viewBox = capture(svg, /viewBox="([^"]+)"/, "SVG viewBox")
    .trim()
    .split(/\s+/)
    .map(Number);
  if (viewBox.length !== 4 || viewBox.some(Number.isNaN)) {
    throw new Error("The SVG viewBox is invalid.");
  }

  const standaloneCss = `
@font-face { font-family: 'JetBrains Mono'; font-weight: 400; src: local('JetBrains Mono'), local('JetBrainsMono-Regular'); }
@font-face { font-family: 'JetBrains Mono'; font-weight: 500; src: local('JetBrains Mono'), local('JetBrainsMono-Regular'); }
@font-face { font-family: 'JetBrains Mono'; font-weight: 600; src: local('JetBrains Mono'), local('JetBrainsMono-Regular'); }
@font-face { font-family: 'JetBrains Mono'; font-weight: 700; src: local('JetBrains Mono'), local('JetBrainsMono-Regular'); }
${css}
:root, svg { ${darkVariables} }
@media (prefers-color-scheme: light) { :root, svg { ${lightVariables} } }
svg[data-theme="light"] { ${lightVariables} }
svg[data-theme="dark"] { ${darkVariables} }
svg {
  font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, 'DejaVu Sans Mono', 'Liberation Mono', 'Noto Sans Mono CJK SC', monospace;
  width: auto;
  min-width: 0;
}
rect.c-bg-rect { fill: var(--bg); }
`.trim();

  svg = svg.replace(
    /<svg\b([^>]*)>/,
    `<svg$1 xmlns="http://www.w3.org/2000/svg" width="${viewBox[2]}" height="${viewBox[3]}">`,
  );
  svg = svg.replace(
    /(<svg\b[^>]*>)/,
    `$1\n<style><![CDATA[\n${standaloneCss}\n]]></style>\n<rect class="c-bg-rect" width="100%" height="100%"/>`,
  );
  await writeFile(outputPath, `${svg}\n`, "utf8");
  console.log(`${basename(inputPath)} -> ${basename(outputPath)}`);
}

const pairs = process.argv.slice(2);
if (!pairs.length || pairs.length % 2 !== 0) {
  throw new Error(
    "Usage: node export_dual_theme_svg.mjs input.html output.svg [...]",
  );
}

for (let index = 0; index < pairs.length; index += 2) {
  await exportSvg(pairs[index], pairs[index + 1]);
}
