#!/usr/bin/env node
// Render every *.mmd in this folder to an SVG beside it with Pele
// (https://pele.run). Install Pele first: `npm install -g pele`.
// Run: node plugins/agentic-team/assets/diagrams/render.mjs
import { execSync } from 'node:child_process';
import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

let pele;
try {
  pele = await import('pele');
} catch {
  const root = execSync('npm root -g', { encoding: 'utf8' }).trim();
  pele = await import(pathToFileURL(join(root, 'pele', 'dist', 'pele.js')).href);
}

const here = dirname(fileURLToPath(import.meta.url));
for (const name of readdirSync(here).filter((f) => f.endsWith('.mmd')).sort()) {
  const id = name.replace(/\.mmd$/, '');
  const { svg, width, height } = pele.render(readFileSync(join(here, name), 'utf8'), { idPrefix: `${id}-` });
  // Paint a background so the SVG reads on dark pages too.
  const filled = svg.replace(/(<svg[^>]*>)/, `$1<rect width="100%" height="100%" fill="var(--_bg)"/>`);
  writeFileSync(join(here, `${id}.svg`), filled + '\n');
  console.log(`${id}.svg ${Math.round(width)}x${Math.round(height)}`);
}
