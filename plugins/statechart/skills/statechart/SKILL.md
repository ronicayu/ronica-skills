---
name: statechart
description: "Check a TLA+ model of a system that moves between states, such as a product flow, a protocol, or a service, and draw it as a Mermaid statechart. The report gives the shortest path to each state that breaks a rule. Use for /statechart, or to show a bug as a path through states."
disable-model-invocation: true
---

# Statechart

Adapted from the statechart skill in [poteto's pstack](https://github.com/cursor/plugins/tree/bb68f2365eceafa0cb2d253112f675acf5f144cc/pstack/skills/statechart), by Lauren Tan (poteto), MIT. "Setup without mise" and the sections after "Hand off" are additions from ronica-skills. `NOTICE.md` at the plugin root lists every change.

The chart shows how a system moves between states, in the words of the person who reads it. That person, the reader, decides whether the behavior is right.

## Run

Work in a scratch folder outside the repo. Write a TLA+ spec and its config. Then run:

```sh
<skill dir>/scripts/statechart SPEC.tla [--config FILE] [--view FILE] [--out DIR]
```

`scripts/statechart.ts` is TypeScript, so run it with a runtime that can execute TypeScript.

The first run installs TLC and Java with mise and needs the network.

## Setup without mise

When `TLA2TOOLS` is set, the runner uses that jar and does not call mise. It runs the jar with `JAVA`, or with `java` on the PATH when `JAVA` is not set. TLC needs Java 11 or later.

Run the setup script once:

```sh
${CLAUDE_PLUGIN_ROOT}/skills/statechart/scripts/setup.sh [CACHE_DIR]
```

The script downloads tla2tools.jar v1.7.4 to `~/.cache/statechart/`, or to `CACHE_DIR`. It checks the sha256 of the jar against `936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88`, the checksum that the runner gives mise. It prints the `export TLA2TOOLS=...` and `export JAVA=...` lines. It also checks for Java and for a runtime that can run the TypeScript. It installs nothing else. It exits 0 when all checks pass.

Install Java yourself. On macOS, run `brew install openjdk`. Homebrew's openjdk is keg-only, so it is not on the PATH. Set `JAVA=/opt/homebrew/opt/openjdk/bin/java`. The macOS `/usr/bin/java` is a stub that fails when no JDK is installed.

The runner needs Node 22.18 to 22.x, Node 23.6 or later, Bun 1.1.5 or later, or Deno 2.0 or later.

Each shell that runs the check needs both variables. Put the export lines in your shell profile, or set the variables on the command line of each run.

## Write the spec

- Write each rule that the reader agrees to as an INVARIANT. A rule can be about a screen, a result, a stored value, or a message. If the model has no variable for a rule, add the variable. Never weaken a rule to make it hold.
- Write `Next` as a disjunction of the actions, such as `YouPressPlay \/ YouPressStop`. If you do not, TLC names every step `Next`.
- A state with no step out breaks `NoDeadlock`, also when it is a correct end state. When an INVARIANT or a PROPERTY already has that name, the rule is `CHECK_DEADLOCK`. Add to `Next` an action that is true only in the end states and changes nothing, such as `Done == phase \in {"paid", "failed"} /\ UNCHANGED vars`, and give it a label in `step()`.

## Pick the chart

You do the work that needs judgment: the words on each state and arrow, the phases and their colors, the title, and the report to the reader. Put your work in a view module, and give it with `--view`.

To show the reader's words, the view exports `state(vars)`. The value that `state()` returns picks the form:

- A string gives a flat chart: `export const state = (v) => (v.paid ? "Paid" : "Paying");`
- An array gives parent states: `export const state = (v) => v.main.split(".");`
- An object gives one parallel region for each key: `export const state = (v) => ({ Playback: v.playback, Volume: v.volume });`

Label each state with what the reader can see or cares about, such as "Paying" or "Lease held, write pending". Keep variable names out of labels. In `vars`, a TLA+ sequence is an object with keys from 1, so `v.pc[1]` is `pc[1]`. A set is an array.

The view can also export `step(action, from, to)`. It gets the TLC action name and the values before and after the step, and it returns the label of the arrow. Write each step label as the user sees it happen, such as "you press play" or "the connect fails". Do not name the code or the TLA+ action. Two actions that end the same in the chart get the same label, so that they share one arrow.

When a step can occur only in some conditions, end its label with the condition in brackets, in the reader's words, such as `you press play [while the file loads]`. In a regions chart, the command writes the condition on the other regions on the arrow, in the words of their labels, such as `[when Offline]`. Your brackets replace it, and two arrows from one state can then look the same. So in a regions chart, do not write brackets for a condition on another region. When a value that no label shows decides where a step goes, name the result in the label, such as "the roster read fails".

The view can also export these:

- `group(vars)` returns the name of a phase. Each chart state gets the color of its group. When the model states behind one chart state are in different groups, that state gets no color.
- `colors` gives each group name a color class.
- `title` is a string that the chart shows at the top.

The command calls `state()` and `group()` at most once for each model state, and `step()` at most once for each step. The chart and the report both use those answers. So make each function depend only on its arguments.

The chart does not draw a step that stays in one label. Split a label when the reader must see such a step.

Aim for about 20 arrows or fewer, because a busier chart is hard to read. First return coarser labels from `state()`. Give one label to values that act the same, and leave out a detail that the reader does not need, such as a call in flight whose return changes nothing. Keep each state of a bug path, and keep each mark. When a merge changes a `breaks` state to `mayBreak`, it hides where a rule breaks. Do not merge two states that break different rules, because the reader then cannot see which rule breaks where. If the chart is still too busy, return `null` from `step()` for the steps that the reader does not need, such as a reset that every state has, or a step whose arrow repeats what other arrows show. Obey these rules when you hide steps:

- Keep each chart state reachable by arrows from a start state.
- Keep at least one arrow out of each chart state that has a step out in the model.
- Hide all the steps of an arrow, or none of them. When you hide only some, its condition gets narrower.
- In the hand-off, say which steps the chart hides.

## Read the report

- In the chart, a state that breaks a rule has the class `breaks`. When only some model states behind it break the rule, it has the class `mayBreak`. The Legend names the rules of each mark. When two rules break, it names both on one mark, so say in the hand-off which state breaks which rule. In a regions chart, a state gets a mark when each combination of region states that includes it can break a rule. When a combination can break a rule and none of its states has a mark, each state in that combination gets a mark.
- TLC goes past a state that breaks a rule, so the chart shows the states after a bug.
- Because TLC goes past bugs, a model with no limit on its states can run without end. Keep the constants small, or add a CONSTRAINT.
- With a VIEW or a SYMMETRY, TLC counts states that it treats as the same as one state, and the chart draws that one state. An arrow can lead to it rather than to the state that the step reaches, and the report says so.
- TLC checks the rules in each state past a CONSTRAINT or an ACTION_CONSTRAINT, but it does not explore that state or check it for deadlock. When TLC's shortest path for a rule ends in such a state, the chart draws that state, and the report gives that path. The chart does not draw the other states past the bound. A deadlock in such a state does not show. TLC also checks the rules after each step that an ACTION_CONSTRAINT excludes, also when it reaches the next state another way. When TLC's shortest path for a rule ends with such a step, the chart draws that step.
- The command checks the rules with TLC on the config as written, with one worker. When a rule breaks, the command removes that rule and runs TLC again, until no rule breaks. After the first break, each run stops at 100,000 distinct states, so that a large model does not run without end. When a run reaches that bound or stops on an error, the report lists the rules that it did not check under "Rules not checked", and the chart does not mark them. A rule that is not checked can hold or break. To check it, remove the rules that break from the config, or make the model smaller. The bound adds a module that changes TLC's order of the variables, so for a property TLC can find a different counterexample than a run without the bound.
- `tlc.out` is what TLC printed on the config as written. When the chart does not show the bug path of a rule that breaks, `tlc-RULE.out` is what TLC printed for the run that found it. When TLC repeats its first warning, plain TLC prints it twice, but `tlc.out` shows it once, because TLC leaves the second copy out of the output that this command reads. That happens only when Java runs with `-XX:+UseParallelGC`, since otherwise TLC's first warning is its advice to pass that flag, which it prints once.

## Show the chart

Show `chart.mmd` to the user as a `mermaid` code block. The chart has a budget of 500 states, counted by TLC on the config as written. Above that, the chart draws only the paths to the rules that break, and when no rule breaks, the command writes no `chart.mmd`. It still checks each rule, and the report gives the state count and each bug path. To see the whole graph, make the model smaller.

Render charts with Pele. When the user asks for an image, or a chart is too large to read as text, follow `references/render.md`. Do not use a different renderer unless the user asks for it.

## Hand off

Give each chart and its Mermaid text to the person who must decide. Add one line for each bug: the rule, the reader's sentence for that rule, and the path as the report numbers it. Say what the model leaves out. Give the command that makes the files again, with a new `--out` folder.

When the model describes code, replay each bug path against the real code, as a test or a live repro, one step for each action. If a bug does not occur, think that the model is wrong until you show that it is not.

## Model code you maintain

Use this method when the model describes code that you can read and change.

- Model the code at one fixed commit. Read each file from that commit with `git show <sha>:<path>`, not from the working tree, which can change while you work. Write the sha at the top of the spec.
- Keep a NOTES file beside the spec. For each action, give the function and the line range that it models, such as `RetryFails: worker.py run_task 120-158`. A reviewer can then check each action against the code.
- Write each rule as a general rule, in the reader's words, such as "a task that has stopped never shows as running". Do not write a rule that names only the bug that you expect. A general rule also finds the bugs that you do not expect.
- Before each run, write your predictions in NOTES: which rules hold, which rules break, and by which path. After the run, compare. A surprise means that the model or your reading of the code is wrong. Find out which before you continue.
- To validate a model, check an older commit with a bug that users found in the field and that a later commit fixed. Model that commit in the same way, and do not tell the model about the bug. TLC must find the bug through a general rule. If it does not, the model leaves out what matters. Fix the model before you trust it on the current commit.

## Peel one dead end per round

TLC reports only the shortest counterexample for each rule. When a rule breaks on a short path, a longer path that breaks the same rule does not show. So a short dead end hides the longer ones.

Work in rounds:

1. Run the model, and take each path in the report.
2. Classify each path. It is real when the code does the same thing. Confirm it in the code, and write the file and the lines in NOTES. It is a model artifact when the code cannot do it. Then fix the model and run again.
3. Give each confirmed break a constant `ALLOW_<NAME>`. When it is TRUE, the model can take the break, as the code does. When it is FALSE, the break is gone. To remove the break, guard the step into the dead end with the constant, or exclude that step with an ACTION_CONSTRAINT. Or add the operator's real way out, such as a manual restart from the runbook.
4. Run one config per round. Each round sets one more `ALLOW_` constant to FALSE. Keep the config and the output of each round, so that the reader can see each break alone.
5. Stop when no rule breaks, or when you know each break.

```tla
CONSTANT ALLOW_LOST_WAKE
\* Round 1: worker.py 120-158 drops the wake signal while the worker sleeps.
\* FALSE removes that step, so the next round finds what the break hid.
WakeLost == ALLOW_LOST_WAKE /\ asleep /\ wake /\ wake' = FALSE /\ UNCHANGED asleep
```

Set `ALLOW_LOST_WAKE = FALSE` in the config of round 2. A guard on the action, as above, is the simplest way to remove a step. When you use an ACTION_CONSTRAINT, remember that TLC still checks the rules in the state after a step that it excludes (see "Read the report"). So when an INVARIANT breaks, exclude a step before the state that breaks it, not the last step into it. A deadlock in an excluded state does not show, so the step into a dead end is safe to exclude.

Never weaken a rule to make it hold. An `ALLOW_` constant removes a break that you confirmed in the code. It does not change a rule. In the hand-off, say which `ALLOW_` constants each round sets to FALSE, because each one hides a real bug.

## Keep the state space small

After the first break, the command stops each rerun at 100,000 distinct states. A rule that a stopped rerun did not check goes under "Rules not checked", and it can hold or break. So keep the model under 100,000 distinct states. The report gives the count. Then each rerun finishes, and TLC checks every rule. Under 500 states, the chart also draws the whole graph.

To cut states safely, merge values that act the same in the code:

- When the code reads only whether a count is zero, model the count as `"none"` or `"some"`, not as a number.
- When two errors take the same branch, model them as one error.
- When the code treats each worker, task, or message the same, model one or two of them, not many.
- Do not merge two values when a branch or a rule tells them apart. Find each branch in the code first. Write in NOTES which values you merged and why.
- A CONSTRAINT also cuts states, but TLC does not check for deadlock past it. Prefer a smaller set of values to a CONSTRAINT.

## Render with the bundled script

`scripts/render.mjs` renders a chart with Pele and the colors of `references/render.md`. Install Pele once, outside the repo, with `npm install -g pele@1.9.0`. Then run:

```sh
node ${CLAUDE_PLUGIN_ROOT}/skills/statechart/scripts/render.mjs OUT/chart.mmd [OUT/chart.svg]
```

The SVG goes beside the chart by default. The script changes two things in the CSS of `references/render.md`:

- It puts the `breaks` and `mayBreak` rules after `bugPath`, and keeps `repeats` last. A state that breaks a rule is also on its bug path. In the order of `references/render.md`, the blue `bugPath` border then hides the red or orange border of the mark. In this order, the border matches the Legend.
- When `report.md` beside the chart says that the chart draws only the bug paths, the script leaves out the `bugPath` border. Above 500 states, every state in the chart is on a bug path, so that border tells the reader nothing.

To make a PNG on macOS, run:

```sh
qlmanage -t -s 2400 -o . chart.svg
sips -c H 2400 --cropOffset 1 0 chart.svg.png --out chart.png
```

`qlmanage` writes `chart.svg.png`, a square of 2400 by 2400 pixels with the chart at the top. For a chart that is wider than it is tall, H is 2400 × height ÷ width of the SVG `viewBox`, rounded up, plus a few pixels. Look at the PNG before you give it to the user. Do not let `sips` render the SVG itself. It ignores the CSS, so the colors and the marks are lost.

## Run it from Claude Code

- The runner is `${CLAUDE_PLUGIN_ROOT}/skills/statechart/scripts/statechart`. Each Bash call starts a new shell, so set the variables on each call: `TLA2TOOLS=$HOME/.cache/statechart/tla2tools.jar JAVA=/opt/homebrew/opt/openjdk/bin/java <runner> SPEC.tla --out out-r1`.
- In auto mode, the permission classifier treats the runner and TLC as downloaded code. It blocks them until the user approves them. A subagent does not inherit that approval. So the main session runs the checks. A subagent can write the spec, the view, and NOTES.
- The `--out` folder must be new or empty. Use a new folder for each run, such as `out-r1` and `out-r2`, so that the output of each round stays. Never run `rm -rf` on a path that comes from a variable. Delete an old folder by its literal name, or leave it.
