// Writes phase-edges.json from TLC's state graph: every step between two phases, as [from, event, to] of
// phase-view.mjs, once each, over all the graphs given. The statechart command draws no chart above 500 states, and
// check.cfg has thousands, so this reads TLC's own graph dump (`-dump dot,actionlabels`) with the statechart skill's
// parser and its view loader. NOTES.md, "The phase edges", gives the commands.
//
//   node phase-edges.mjs GRAPH.dot... > phase-edges.json

import fs from "node:fs";
import util from "node:util";
import { parseDot } from "../../statechart/skills/statechart/scripts/frontends/dot.ts";
import { checkView } from "../../statechart/skills/statechart/scripts/frontends/view.ts";
import * as phaseView from "./phase-view.mjs";

const files = process.argv.slice(2);
if (!files.length) {
  console.error("Usage: node phase-edges.mjs GRAPH.dot... > phase-edges.json");
  process.exit(2);
}
const view = checkView(phaseView, util.inspect);
const edges = new Set();
for (const file of files) {
  const graph = parseDot(fs.readFileSync(file, "utf8"));
  for (const { from, to, action } of graph.steps) {
    const before = graph.states.get(from).vars;
    const after = graph.states.get(to).vars;
    const was = view.state(before);
    const is = view.state(after);
    if (was !== is) edges.add(JSON.stringify([was, view.step(action, before, after), is]));
  }
}
const about = "The steps between phases of Lifecycle.tla in check.cfg and check-pr.cfg, as [from, event, to] of " +
  "phase-view.mjs (\"none\" is run.py's None). Written by phase-edges.mjs; tests/test_run.py checks them against TRANSITIONS.";
process.stdout.write(`{\n  "about": ${JSON.stringify(about)},\n  "edges": [\n${
  [...edges].sort().map((e) => `    ${e}`).join(",\n")}\n  ]\n}\n`);
