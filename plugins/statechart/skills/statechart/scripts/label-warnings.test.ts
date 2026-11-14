import assert from "node:assert/strict";
import { test } from "node:test";
import { inspect } from "node:util";
import { checkView } from "./frontends/view.ts";
import type { CheckResult, Graph, Vars } from "./ir.ts";
import { compile } from "./pipeline.ts";

type Edge = [from: string, action: string, to: string];

function run(
  names: string[],
  edges: Edge[],
  view: { [name: string]: unknown },
): { report: string; chart: string } {
  const graph: Graph = { states: new Map(), steps: [] };
  for (const [i, name] of names.entries())
    graph.states.set(name, { vars: { at: name }, start: i === 0, breaks: [] });
  for (const [from, action, to] of edges) graph.steps.push({ from, to, action });
  const result: CheckResult = {
    spec: {
      module: "Demo",
      variables: ["at"],
      invariants: [],
      properties: [],
      deadlock: false,
      written: [],
      folder: "",
    },
    graph,
    paths: undefined,
    rules: [],
    properties: [],
    exit: 0,
    stop: undefined,
    drawing: undefined,
    states: { distinct: names.length, initial: 1, complete: true, cut: false },
    messages: [],
  };
  const { report, files } = compile(result, checkView(view, inspect));
  const chart = files.get("chart.mmd");
  assert.ok(chart);
  return { report, chart: [...chart].join("") };
}

const label = (vars: Vars) => String(vars.at);

const section = (report: string, name: string) => {
  const start = report.indexOf(`## ${name}\n`);
  assert.notEqual(start, -1, `report has no ${name} section`);
  const next = report.indexOf("\n## ", start + 1);
  return report.slice(start, next === -1 ? undefined : next);
};

const view = (steps: { [action: string]: string }, extra = {}) => ({
  state: label,
  step: (action: string) => steps[action] ?? action,
  ...extra,
});

const NAMES = ["Task session open", "Task session closed", "Task session failed"];

test("a clean chart has no label warnings", () => {
  const { report } = run(
    NAMES,
    [
      ["Task session open", "Close", "Task session closed"],
      ["Task session open", "Fail", "Task session failed"],
    ],
    view({ Close: "the Manager closes the task", Fail: "the worker reports a failure" }),
  );
  assert.match(report, /The chart has 0 label warnings\./);
  assert.match(section(report, "Label warnings"), /No label has a warning\./);
});

test("an arrow label that starts with a pronoun is flagged", () => {
  for (const text of ["you close the task", "It closes the task", "We close the task now"]) {
    const { report } = run(
      NAMES,
      [["Task session open", "Close", "Task session closed"]],
      view({ Close: text }),
    );
    assert.match(section(report, "Label warnings"), /starts with a pronoun/, text);
  }
  const { report } = run(
    NAMES,
    [["Task session open", "Close", "Task session closed"]],
    view({ Close: "I/O operators close the task" }),
  );
  assert.doesNotMatch(report, /starts with a pronoun/);
});

test("a Chinese label that starts with a pronoun is flagged", () => {
  const { report } = run(
    NAMES,
    [["Task session open", "Close", "Task session closed"]],
    view({ Close: "我们关闭任务会话" }),
  );
  assert.match(section(report, "Label warnings"), /"我们关闭任务会话".*starts with a pronoun/);
});

test("a state label that starts with a pronoun is flagged", () => {
  const { report } = run(
    ["It is open", "Task session closed"],
    [["It is open", "Close", "Task session closed"]],
    view({ Close: "the Manager closes the task" }),
  );
  assert.match(section(report, "Label warnings"), /The state label "It is open" starts with a pronoun/);
});

test("a state label of fewer than 2 words, an arrow label of fewer than 3, or fewer than 4 CJK characters, is flagged", () => {
  const { report } = run(
    ["Open", "Task closed"],
    [["Open", "Close", "Task closed"]],
    view({ Close: "Manager closes" }),
  );
  const text = section(report, "Label warnings");
  assert.match(text, /The state label "Open".*too short/);
  assert.match(text, /The arrow label "Manager closes".*too short/);
  assert.doesNotMatch(text, /The state label "Task closed"/);
  const cjk = run(
    ["任务会话已打开", "任务会话已关闭"],
    [["任务会话已打开", "Close", "任务会话已关闭"]],
    view({ Close: "经理关" }),
  );
  const warned = section(cjk.report, "Label warnings");
  assert.match(warned, /"经理关".*too short/);
  assert.doesNotMatch(warned, /The state label/);
});

test("a bracketed condition counts as part of the label", () => {
  const { report } = run(
    NAMES,
    [["Task session open", "Close", "Task session closed"]],
    view({ Close: "the Manager closes [the task is done]" }),
  );
  assert.match(report, /The chart has 0 label warnings\./);
});

test("arrows that leave one state with one label and go to different states are flagged", () => {
  const { report } = run(
    NAMES,
    [
      ["Task session open", "Close", "Task session closed"],
      ["Task session open", "Fail", "Task session failed"],
    ],
    view({ Close: "the Manager closes the task", Fail: "the Manager closes the task" }),
  );
  const text = section(report, "Label warnings");
  assert.match(
    text,
    /2 arrows leave "Task session open" with the label "the Manager closes the task" and go to different states: "Task session closed", "Task session failed"/,
  );
});

test("labels that differ by a condition in brackets are not flagged as the same", () => {
  const { report } = run(
    NAMES,
    [
      ["Task session open", "Close", "Task session closed"],
      ["Task session open", "Fail", "Task session failed"],
    ],
    view({
      Close: "the Manager closes the task [it passed]",
      Fail: "the Manager closes the task [it failed]",
    }),
  );
  assert.doesNotMatch(report, /go to different states/);
});

test("a label that the tool joined with or is flagged", () => {
  const { report } = run(
    NAMES,
    [
      ["Task session open", "Close", "Task session closed"],
      ["Task session open", "Done", "Task session closed"],
    ],
    view({ Close: "the Manager closes the task", Done: "the worker ends the task" }),
  );
  assert.match(
    section(report, "Label warnings"),
    /The tool joined 2 labels into "the Manager closes the task or the worker ends the task" from "Task session open" to "Task session closed"/,
  );
});

test("the Arrows table lists label, states, deduplicated actions and step count", () => {
  const { report } = run(
    ["Task session open", "Task session closed"],
    [
      ["Task session open", "Close", "Task session closed"],
      ["Task session open", "CloseFast", "Task session closed"],
      ["Task session open", "Close", "Task session closed"],
    ],
    view({ Close: "the Manager closes the task", CloseFast: "the Manager closes the task" }),
  );
  assert.equal(
    section(report, "Arrows").trim(),
    [
      "## Arrows",
      "| Label | From | To | TLA+ actions | Steps |",
      "| --- | --- | --- | --- | --- |",
      "| the Manager closes the task | Task session open | Task session closed | Close, CloseFast | 3 |",
    ].join("\n"),
  );
});

test("the glossary shows in the Legend", () => {
  const { chart } = run(
    ["Task session open", "Task session closed"],
    [["Task session open", "Close", "Task session closed"]],
    view(
      { Close: "the Manager closes the task" },
      { glossary: { Manager: "the person who plans the work" } },
    ),
  );
  assert.match(chart, /state "Legend" as legend \{/);
  assert.match(chart, /state "Terms" as terms \{\n\s+tm0: Manager = the person who plans the work\n\s+\}/);
});

test("a chart without a glossary has no Legend", () => {
  const { chart } = run(
    ["Task session open", "Task session closed"],
    [["Task session open", "Close", "Task session closed"]],
    view({ Close: "the Manager closes the task" }),
  );
  assert.doesNotMatch(chart, /Legend|Terms/);
});

test("the view rejects a glossary that is not a map of strings", () => {
  assert.throws(() => checkView({ glossary: "Manager" }, inspect), /glossary must be a plain object/);
  assert.throws(() => checkView({ glossary: { Manager: 3 } }, inspect), /glossary gives "Manager" the value 3/);
  assert.throws(() => checkView({ glossary: { Manager: " " } }, inspect), /glossary gives/);
});
