/**
 * Frontend coverage per area (core, shared, app, each feature) — the same view CI gives the backend.
 *
 *   npm run coverage && node scripts/coverage-summary.mjs [--summary FILE] [--badge FILE]
 *
 * Reads coverage/coverage-summary.json (vitest, v8 provider). Prints a Markdown table (appended to
 * `--summary`, e.g. $GITHUB_STEP_SUMMARY) and writes a shields.io endpoint JSON to `--badge`.
 * The floors themselves live in vite.config.js (`test.coverage.thresholds`) and fail `npm run coverage`.
 */
/* eslint-disable no-console -- CI helper: stdout is its interface */
import { appendFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const option = (name) => (args.includes(name) ? args[args.indexOf(name) + 1] : null);

const summary = JSON.parse(readFileSync(resolve(root, 'coverage/coverage-summary.json'), 'utf8'));
const areaOf = (file) => {
  const parts = relative(resolve(root, 'src'), file).split(/[\\/]/);
  return parts[0] === 'features' ? `features/${parts[1]}` : parts[0];
};

const areas = new Map();
for (const [file, data] of Object.entries(summary)) {
  if (file === 'total') continue;
  const area = areas.get(areaOf(file)) ?? { covered: 0, total: 0 };
  for (const kind of ['statements', 'branches']) {
    area.covered += data[kind].covered;
    area.total += data[kind].total;
  }
  areas.set(areaOf(file), area);
}
const percent = ({ covered, total }) => (total ? (100 * covered) / total : 100);
const t = summary.total;
const overall = percent({ covered: t.statements.covered + t.branches.covered, total: t.statements.total + t.branches.total });

const rows = [...areas.entries()].sort((a, b) => percent(a[1]) - percent(b[1]));
const text = [
  `### Frontend coverage: ${overall.toFixed(1)}% (statements ${t.statements.pct}% · branches ${t.branches.pct}% · functions ${t.functions.pct}%)`,
  '',
  '| Area | Coverage | Statements + branches |',
  '| --- | ---: | ---: |',
  ...rows.map(([name, a]) => `| \`${name}\` | ${percent(a).toFixed(1)}% | ${a.total} |`),
].join('\n');
console.log(text);

const summaryFile = option('--summary');
if (summaryFile) appendFileSync(summaryFile, `${text}\n`);
const badgeFile = option('--badge');
if (badgeFile) {
  mkdirSync(dirname(resolve(badgeFile)), { recursive: true });
  const color = overall >= 80 ? 'brightgreen' : overall >= 60 ? 'green' : overall >= 40 ? 'yellow' : 'orange';
  writeFileSync(badgeFile, JSON.stringify({ schemaVersion: 1, label: 'frontend coverage', message: `${Math.round(overall)}%`, color }));
}
