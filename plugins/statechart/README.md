# statechart

Adapted from the statechart skill in
[poteto's pstack](https://github.com/cursor/plugins/tree/bb68f2365eceafa0cb2d253112f675acf5f144cc/pstack/skills/statechart),
by Lauren Tan (poteto), MIT. See [NOTICE.md](NOTICE.md) for what is vendored
and what we changed.

## What it does

You write a TLA+ model of a system that moves between states, such as a
product flow, a protocol, or a service. The skill checks the model with TLC
and draws it as a Mermaid statechart, in the words of the person who must
decide whether the behaviour is right. The report gives the shortest path to
each state that breaks a rule.

Call it with `/statechart`, or let Claude or another agent pick it up when a
change touches state-machine or lifecycle logic, or code that a repository
already models with it. Upstream sets `disable-model-invocation: true`; this
copy does not (see NOTICE.md).

## Install

```text
/plugin marketplace add ronicayu/ronica-skills
/plugin install statechart@ronica-skills
```

## Setup

Paths are relative to this plugin folder. As an installed plugin, that is
`${CLAUDE_PLUGIN_ROOT}`.

The runner needs:

- TLC (tla2tools.jar) and Java 11 or later.
- Node 22.18 to 22.x, Node 23.6 or later, Bun 1.1.5 or later, or Deno 2.0 or
  later, to run its TypeScript.
- Pele, to render charts as SVG: `npm install -g pele@1.9.0`.

With [mise](https://mise.jdx.dev), the first run installs TLC and Java.
Without mise, install Java yourself (macOS: `brew install openjdk`), then run:

```sh
skills/statechart/scripts/setup.sh [CACHE_DIR]
```

It downloads tla2tools.jar v1.7.4 to `~/.cache/statechart/` (or `CACHE_DIR`),
checks its sha256, checks for Java and a TypeScript runtime, and prints the
`TLA2TOOLS` and `JAVA` export lines. Put those lines in your shell profile.
Homebrew's openjdk is keg-only, so `JAVA` must name
`/opt/homebrew/opt/openjdk/bin/java`.

## Use

```sh
TLA2TOOLS=... JAVA=... skills/statechart/scripts/statechart SPEC.tla [--config FILE] [--view FILE] [--out DIR]
node skills/statechart/scripts/render.mjs DIR/chart.mmd
```

The first command writes `report.md`, `chart.mmd`, and TLC's output to a new
`--out` folder. The second writes `chart.svg` beside the chart. `SKILL.md`
explains how to write the spec and the view, and how to read the report.

## Our additions

In `SKILL.md`:

- **Setup without mise**: the `TLA2TOOLS` and `JAVA` variables and the setup
  script.
- **Model code you maintain**: model one fixed commit from source, map each
  action to code lines in a NOTES file, write general rules in the reader's
  words, write predictions before each run, and validate the model on an older
  commit with a known field bug.
- **Peel one dead end per round**: TLC shows only the shortest counterexample
  for each rule. Remove each confirmed break with an `ALLOW_*` constant, and
  run one config per round.
- **Keep the state space small**: stay under the 100,000-state rerun bound so
  that every rule is checked, and merge only values that act the same in the
  code.
- **Render with the bundled script**: bug-mark borders that match the Legend,
  and PNG export on macOS.
- **Run it from Claude Code**: the permission classifier, subagents, and one
  `--out` folder per run.

- **Label checks (0.3.0)**: the view may export `glossary` (`{term:
  definition}`), which the chart shows in its Legend under "Terms".
  `report.md` has a "Label warnings" section and an "Arrows" table, and its
  first lines say how many warnings the chart has.
  - A warning names a label that starts with a pronoun (you, I, we, it, they,
    he, she, or 你, 我, 我们, 它, 他, 她, 他们), a label of fewer than 3 words
    (fewer than 4 characters for CJK text), arrows that leave one state with
    the same label and go to different states, and a label that the tool
    joined with " or ". Text in brackets counts as part of the label.
  - The "Arrows" table has one row for each drawn arrow: label, from state,
    to state, the TLA+ actions behind it, and the number of model steps.

Scripts: `scripts/setup.sh` and `scripts/render.mjs`.

Type check: `npm install && npm run typecheck` in `skills/statechart/scripts/`
runs `tsc --noEmit`; CI runs it on every PR. `NOTICE.md` lists the two changes
to upstream code that make it pass.

Tests: `npm test` in the same folder runs the label checks with `node --test`.
They build a small graph, so they need no TLC and no Java.

## License

MIT. See [LICENSE](LICENSE): Lauren Tan for the upstream skill, Yu Rong for
the additions.
