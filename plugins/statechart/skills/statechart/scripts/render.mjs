#!/usr/bin/env node
// Render a statechart chart.mmd to SVG with Pele (https://pele.run).
//
// Usage: node render.mjs CHART.mmd [OUT.svg]
//
// OUT.svg defaults to CHART.svg beside the input. Install Pele first, outside
// the repo: `npm install -g pele@1.9.0`.
//
// The CSS is the one in references/render.md, with two changes:
// - The bug marks (breaks, mayBreak) come after bugPath, so that a state that
//   breaks a rule shows the mark's border, as the Legend says. repeats stays last.
// - When report.md beside the chart says that "the chart draws only the bug
//   paths", the bugPath border is left out: every drawn state is on a bug path.
//
// Part of ronica-skills; not from upstream pstack (see NOTICE.md).
import { execSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, dirname, join } from 'node:path';
import { pathToFileURL } from 'node:url';

const USAGE = 'Usage: node render.mjs CHART.mmd [OUT.svg]';

const args = process.argv.slice(2);
if (args.length < 1 || args.length > 2 || args.some((a) => a === '-h' || a === '--help')) {
  console.error(USAGE);
  process.exit(args.length === 0 || args.length > 2 ? 2 : 0);
}
const input = args[0];
const output = args[1] ?? join(dirname(input), `${basename(input).replace(/\.mmd$/, '')}.svg`);

let pele;
try {
  pele = await import('pele');
} catch {
  try {
    const root = execSync('npm root -g', { encoding: 'utf8' }).trim();
    pele = await import(pathToFileURL(join(root, 'pele', 'dist', 'pele.js')).href);
  } catch {
    console.error('Cannot load Pele. Install it with: npm install -g pele@1.9.0');
    process.exit(2);
  }
}

// --- CSS from references/render.md, in this order: base, group colors,
// --- bugPath, the bug marks, then repeats.

const base = `.pele {
  --pele-bg: #ffffff;
  --pele-fg: #1c1c1c;
  --pele-muted: #656565;
  --pele-line: #808080;
  --pele-surface: #fcfcfc;
  --pele-surface-alt: #f1f1f1;
  --pele-border: #c9c9c9;
}
.pele .blue rect { fill: #c3e0ff; }
.pele .orange rect { fill: #f0d3bf; }
.pele .purple rect { fill: #e3d5ff; }
.pele .yellow rect { fill: #f0dcbf; }
.pele .teal rect { fill: #bfe3df; }
.pele .tan rect { fill: #e5d9ce; }
.pele .pink rect { fill: #ffcbe6; }
`;
const bugPath = `.pele .bugPath rect {
  stroke: #1680f3 !important;
  stroke-width: 2.5px !important;
}
`;
const repeats = `.pele .repeats rect {
  stroke: #9b35d6 !important;
  stroke-width: 2.5px !important;
  stroke-dasharray: 6 3;
}
`;
const marks = `.pele .breaks rect {
  fill: #ffecee !important;
  stroke: #e72e3b !important;
  stroke-width: 2.5px !important;
}
.pele .breaks text {
  fill: #cd2834 !important;
}
.pele .mayBreak rect {
  fill: #fff3e6 !important;
  stroke: #e8730c !important;
  stroke-width: 2.5px !important;
}
.pele .mayBreak text {
  fill: #b85a06 !important;
}
`;
const darkBase = `  .pele {
    --pele-bg: #1f1f1f;
    --pele-fg: #f5f5f5;
    --pele-muted: #acacac;
    --pele-line: #939393;
    --pele-surface: #121212;
    --pele-surface-alt: #2c2c2c;
    --pele-border: #4e4e4e;
  }
  .pele .blue rect { fill: #1b3857; }
  .pele .orange rect { fill: #573117; }
  .pele .purple rect { fill: #3c2e57; }
  .pele .yellow rect { fill: #573d17; }
  .pele .teal rect { fill: #174641; }
  .pele .tan rect { fill: #3d3127; }
  .pele .pink rect { fill: #57233e; }
`;
const darkBugPath = `  .pele .bugPath rect {
    stroke: #116dd2 !important;
  }
`;
const darkRepeats = `  .pele .repeats rect {
    stroke: #9a3fcf !important;
  }
`;
const darkMarks = `  .pele .breaks rect {
    fill: #2e2021 !important;
    stroke: #cf2b35 !important;
  }
  .pele .breaks text {
    fill: #ff6463 !important;
  }
  .pele .mayBreak rect {
    fill: #2e2619 !important;
    stroke: #d0700f !important;
  }
  .pele .mayBreak text {
    fill: #ffa257 !important;
  }
`;

// The sentence that backends/report.ts writes when the chart is over budget.
const report = join(dirname(input), 'report.md');
let pathsOnly = false;
if (existsSync(report)) {
  pathsOnly = readFileSync(report, 'utf8').includes('the chart draws only the bug paths');
} else {
  console.error(`No report.md beside ${input}; keeping the bugPath border.`);
}

const css =
  base +
  (pathsOnly ? '' : bugPath) +
  marks +
  repeats +
  '@media (prefers-color-scheme: dark) {\n' +
  darkBase +
  (pathsOnly ? '' : darkBugPath) +
  darkMarks +
  darkRepeats +
  '}\n';

const idPrefix = `${basename(output).replace(/\.svg$/, '').replace(/\W/g, '') || 'chart'}-`;
let result;
try {
  result = pele.render(readFileSync(input, 'utf8'), {
    limit: 1_000_000,
    outputLimit: 8_000_000,
    maxEdges: 10_000,
    idPrefix,
  });
} catch (e) {
  // Pele throws a PeleError on a chart it cannot draw. Show the user the
  // Mermaid text and this error.
  console.error(`Pele could not render ${input}: ${e?.name ?? 'Error'}: ${e?.message ?? e}`);
  process.exit(1);
}

// The style goes first, then a background that follows --pele-bg, so the SVG
// reads in light and dark viewers.
const svg = result.svg.replace(
  /(<svg[^>]*>)/,
  `$1<style>${css}</style><rect width="100%" height="100%" fill="var(--_bg)"/>`,
);
writeFileSync(output, svg + '\n');
console.log(
  `${output} ${Math.round(result.width)}x${Math.round(result.height)}${pathsOnly ? ' (bug paths only: no bugPath border)' : ''}`,
);
