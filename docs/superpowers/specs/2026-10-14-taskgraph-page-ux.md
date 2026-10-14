# taskgraph graph page: UX fixes for steering use

Date: 2026-10-14. Plugin version after this work: 1.9.0.

Scope: `plugins/taskgraph/skills/taskgraph/scripts/graph_template.html` (the page), `plugins/taskgraph/skills/taskgraph/tests/test_page.py` (tests), `plugins/taskgraph/skills/taskgraph/SKILL.md` (wording), three manifest version fields. No change to `tg.py`: every item below is page-side. Line numbers refer to the template as of 1.8.0.

## Design principles

- Audience: a programme director who runs several workstreams and presents the page to a steering committee for about five minutes. The agent drives the CLI; the director only looks. Nothing on the page is for editing.
- Two modes, one page. **Presenting**: a projector at 1920×1080 or a laptop at 1280×720, the mouse resting on the canvas, no time to zoom. Text must be legible at the zoom the page picks, and nothing may vanish because the mouse moved. **Analysing**: the director clicks around, searches, focuses a goal. Every state must be reachable by URL and by keyboard.
- The question order is fixed: what is late, what is at risk, will milestone X land, who owns what, what needs a decision. Words carry status; colour only reinforces it.
- One vocabulary with the CLI and `report`: the same RAG rules, the same `#id` prefixes, the same words ("at risk", "conflict", "late").
- Keep from the review's "don't change" list: Hide done on by default; Conflicts only as the default Dependencies mode; shape per type; milestones first within a lane and undated items in their own band at the bottom; goal picker ordered by date with done items last; `#id` prefix on every label; bridged dashed edges when types are filtered.

## Shared definitions (used by several items)

- `READABLE = 0.9`. The zoom below which labels are unreadable. One constant, all views. It replaces `TL.readable`.
- `todayYear = (DATA.today || new Date().toLocaleDateString('sv')).slice(0, 4)`.
- `inheritedMeta(n, key)`: returns the first non-empty trimmed string value of `meta[key]` walking `n`, then `byId.get(n.parent)`, then its parent, and so on; `null` when none. Mirrors `inherited()` in `tg.py` (line 162). Decision: implemented page-side because `lane`/`team` are not in `NODE_FIELDS` (`tg.py` line 61) and the preference is no Python change.
- `laneOf(n)`: `v = LANE_KEYS[laneKey](n)`; when `v` is null or blank, returns `'Objectives'` if `n.type === 'objective'`, else `'Unassigned'`; otherwise `String(v).trim()`.
- Band order (both Swimlane and Timeline): `Objectives` first, then every other lane case-insensitively alphabetical, then `Unassigned`, then (Timeline only) `Undated`.
- `bandRag(name)`: `ragOf(DATA.nodes.filter(n => keeps(n) && laneOf(n) === name && (!isSummary(n) || n.type === 'objective')))`. It respects project, goal and Hide done (`keeps`, line 363) and ignores the type filter, expansion state and view. `ragOf` is unchanged (line 184). Every stripe in both views is built from this function.

## Items

### 1. C1: Timeline lanes match workstreams; lane RAG is consistent across views

Problem: `layoutTimeline` nests any dated child under its parent row (line 727), so the whole programme tree sits under the objective in a band named "Unassigned", workstream lanes look empty, and the stripe (line 775) is computed from the visible rows, so Data reads green in the Timeline and amber in the Swimlane.

Required behaviour:

- A Timeline row is top-level when `!datesOf(n) || !shown.has(n.parent) || laneOf(n) !== laneOf(byId.get(n.parent))`. A child nests (indented, `depth + 1`) under its parent only when the parent is shown, the child is dated and both have the same `laneOf`. `kids` (line 724) is filtered the same way.
- Top-level dated rows are grouped by `laneOf(n)`; undated rows go to `Undated` as today. Bands are ordered as in Shared definitions. Within a band the sort is unchanged (`cmp`, line 725: milestones first, then start date, then id).
- Objectives with no lane value sit in a band headed `Objectives` (not `Unassigned`) in both views. Their summary bar still spans `n.span` from the CLI even when their children are drawn in other bands.
- The Swimlane (`layoutLanes`, line 576) uses the same `laneOf` and band order. Node placement in columns is unchanged.
- Both views colour each stripe with `bandRag(name)`. Stripe `data.rag` keeps the value for tests. Collapsing or expanding, or filtering types, never changes a stripe.

Where: `laneOf` (line 475), `LANE_KEYS.lane` → `n => inheritedMeta(n, 'lane')`, `stripe()` (line 185, takes a band name instead of a node list), `layoutLanes` names sort (line 593), `layoutTimeline` grouping, `kids`, `names` sort and the two `spans.forEach` (lines 724–776).

Tests (`test_page.py`), new module fixture `programme_file` built with `runner(tmp / "t.db")` (today is 2026-10-13):

```
tg("add", "Migrate", "--type", "objective", "--meta", "owner=pd")                                   # 1
tg("add", "Go live", "--type", "milestone", "--due", "2026-12-15", "--meta", "lane=Programme")      # 2
tg("add", "Build landing zone", "--parent", "1", "--meta", "lane=Infra", "owner=priya")            # 3
tg("add", "Write modules", "--parent", "3", "--start", "2026-09-20", "--due", "2026-10-10", "--meta", "owner=priya")  # 4, late, inherits Infra
tg("add", "Migrate data", "--parent", "1", "--meta", "lane=Data", "owner=mei")                     # 5
tg("add", "Replicate", "--parent", "5", "--start", "2026-10-15", "--due", "2026-11-15", "--meta", "owner=mei")        # 6
tg("add", "Capacity", "--type", "risk", "--blocks", "6", "--due", "2026-10-20", "--meta", "lane=Data", "owner=priya", "likelihood=medium", "impact=high")  # 7
tg("add", "Residency", "--type", "decision", "--due", "2026-10-25", "--meta", "lane=Security", "decider=ciso")        # 8
tg("dep", "add", "2", "3"); tg("dep", "add", "2", "5"); tg("dep", "add", "6", "8")
```

- `test_bands_and_rag_match_across_views`: for `view in ("lanes", "timeline")`, band heads in y order are `["Objectives", "Data", "Infra", "Programme", "Security"]` (Swimlane: `cy.nodes('.lane-bg').map(n => n.data('name'))` after stripping the RAG suffix from item 8; Timeline: `cy.nodes('.tl-head')`). `cy.nodes('.lane-rag').map(n => n.data('rag'))` in the same order equals `["red", "amber", "red", "red", "amber"]` in both views (Infra is red from collapsed #4; Data amber from collapsed #6's conflict). Click `#expandAll`; the array is unchanged.
- `test_timeline_nests_only_within_lane`: Timeline, after `#expandAll`: the row names in y order contain `"Infra"`, then `"▾ #3 Build landing zone"`, then `"#4 Write modules"` with `data('tx') == 14 + 14 - TL.names`; `"#3 Build landing zone"` is not between `"Objectives"` and `"Data"`.
- Update `test_timeline_dependency_modes_and_pinned_milestones`: with `page_file` the task rows in y order are now `["▾ #1 Launch", "#2 Ship v1", "#3 Build feature", "#5 Vendor key", "#4 Write docs", "#6 Undated chore"]` and the heads are `["Objectives", "dev", "docs", "Undated"]`.
- `test_lane_rag_stripes` keeps passing unchanged.

Must not regress: `?goal=` scope (`bandRag` goes through `keeps`, so a goal narrows the stripe to what the goal needs, which is the intended reading); `?lanes=owner|tag|project`; critical-path and conflict edge routing (`marks` is still keyed by node id, lines 770 and 796); milestones pinned first; `applyData` (`sameShape` is unaffected; `layout(false)` rebuilds bands).

### 2. C2: readability floor and larger labels

Problem: every view fits the whole plan into the viewport. Measured: Graph at 1440×900 renders the 12 px label at 7.3 px, at 1280×720 at 5.3 px, on a 1920×1080 projector at 9.4 px; a 100-node plan hits `minZoom` 0.1. The Timeline's `TL.readable` floor is skipped after Expand all and Fit.

Required behaviour:

- Sizes: node `font-size` 12 → 13 (line 242); `ctx.font = 'bold 13px ' + FONT` (line 202); `NODE_W` 180 → 200 (`LABEL_W` follows); `MILESTONE_LANE_W` 102 → 112, `DECISION_LANE_W` 136 → 150; Swimlane milestone label 10 → 11 (line 265); `lane-bg` header 12 → 13 (line 271); `node.tl` label 11 → 12 (line 285); `tl-name` 12 → 13 (line 304); `tl-grid` 11 → 12; `TL.names` 260 → 290; `TL.row` 26 → 28. `COL_W` 240 → 260, `ROW_H` 84 → 88.
- `fitView()` becomes: `t = fitTarget(); if (!t) return; if (t.zoom < READABLE) t = anchored(READABLE); cy.viewport(t)`.
- `anchored(zoom)` returns `{zoom, pan}` where, with `box = $('cy').getBoundingClientRect()`:
  - Graph: anchor node = the visible goal node when `goal` is set, else the visible objective with the lowest id, else the visible node with the smallest model `y`. Pan so the anchor's rendered centre x is `box.width / 2` and its rendered top edge is 40 px below the top of `#cy`.
  - Swimlane and Timeline: pan so the model bounding box corner `(x1, y1)` lands at `(40, 40)` inside `#cy` (the existing Timeline rule, line 801).
- The floor applies wherever `fitView()` runs: first load, Fit, Re-layout, view switch, project/goal/type change, and item 13. It never applies to user wheel/drag zoom; `minZoom` stays 0.1.
- `covered()` (line 833) returns `false` whenever `fitTarget().zoom < READABLE` (the plan cannot be shown whole, so nodes are legitimately off-screen). Otherwise it is unchanged. `fitIfOutside()` therefore never shrinks a floored view.
- Remove `TL.readable` and the special case at lines 799–802.

Where: constants lines 150–152; styles listed above; `fitView`/`fitTarget`/`covered` (lines 818–846); `layoutTimeline` tail.

Tests: new module fixture `tall_file`: objective `Programme` then 40 tasks `Step N` in `lane=dev`, each with `--depends` on the previous, dated weekly from 2026-10-20. For each view at 1400×900: `abs(cy.zoom() - 0.9) < 1e-6` after load, after `#fit`, and after `#expandAll`; the anchor node (`#1` in Graph) has `renderedBoundingBox().y1 >= 0` and `x2 <= box.width`; `covered()` is `False`. With `page_file` (small): `cy.zoom() > 0.9` and every task node inside the viewport (existing `test_fit_keeps_nodes_clear_of_legend` keeps passing unchanged). CJK: a `clampLabel('完成所有租户的数据迁移并验证数据一致性以及回滚方案的演练', LABEL_W, 2)` evaluated in the page yields exactly 2 lines, the last ending in `…`.

Must not regress: legend reserve in `fitTarget` (unchanged); `?view=` and `?goal=` (fit runs after the URL state is applied, as now); `applyData` keeps its `fitIfOutside` call; critical path unaffected.

### 3. H1: a toolbar that never overflows or scrolls the pickers away

Problem: `#toolbar` is a fixed 48 px flex row with `overflow-x: auto` and `flex: none` children (lines 10–11). Its content is 1602 px wide, so at 1440 and below Re-layout, Fit and the stamp are off-screen, and clicking Fit scrolls the toolbar (`scrollLeft` 536) so the project and goal pickers disappear.

Required behaviour:

- `#toolbar { position: fixed; top: 0; left: 0; right: 0; display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; padding: 6px 14px; min-height: 48px; overflow: visible; }`. Remove `height: 48px` and `overflow-x: auto`. `#goal { flex: 0 1 auto; max-width: min(320px, 40vw); }`. The `.spacer` and `.stamp` rules stay, so the stamp sits at the right end of the last row.
- `#cy` and `#panel` use `top: var(--bar)`. A `ResizeObserver` on `#toolbar` sets `document.documentElement.style.setProperty('--bar', toolbar.offsetHeight + 'px')` then calls `cy.resize()`. Initial value set once before the first `rebuild()`.
- DOM order of controls is unchanged, with `#searchCount` (item 4) inserted after `#search`. Expected rows: one row at 1920 in Graph and Swimlane, two rows at 1440 and 1280 (and at 1920 in Timeline), at most three rows at 1024.

Where: CSS lines 10–32 and 42; a small block before `fillGoals(); rebuild();` at line 1220.

Tests: `test_toolbar_never_overflows`: for width in (1024, 1280, 1440, 1920) and each view, with `page_file`: `toolbar.scrollWidth <= toolbar.clientWidth`; every `#toolbar > *:not([hidden])` has `getBoundingClientRect().right <= width` and `.left >= 0`; `toolbar.offsetHeight <= (140 if width == 1024 else 96)`; `#cy.getBoundingClientRect().top == toolbar.getBoundingClientRect().bottom`; after `page.click('#fit')` and `page.click('#expandAll')`, `toolbar.scrollLeft == 0` and `#project`'s `rect.left >= 0`.

Must not regress: `fitTarget` uses `#cy`'s rect, so it follows `--bar` automatically; the legend's `bottom: 14px` is unaffected; panel top follows the same variable.

### 4. H2: search finds collapsed items, gives feedback, Enter cycles hits

Problem: `applySearch` (line 977) dims only visible nodes; "contain" matches two tasks inside a collapsed summary, so every node dims and nothing says why.

Required behaviour:

- Hits: `DATA.nodes.filter(n => passes(n) && (title.toLowerCase().includes(q) || ('#' + n.id).includes(q)))`, `q` trimmed and lower-cased. `passes` (line 369) already applies project, goal, Hide done and the type filter.
- On input (debounced 150 ms): if `q` is non-empty, add every ancestor of every hit to the expanded set (`setExpanded`, as `reveal()` does) and `rebuild(true)` when the set grew; then dim every task node that is not a hit (`.dim`). If `q` is empty, nothing is dimmed and nothing is expanded.
- `<span id="searchCount" aria-live="polite">` after `#search`, colour `#9ca3af`, 12 px. Text: empty when `q` is empty; `"No matches"` when zero; `"1 match"`; `"N matches"` otherwise.
- Keys inside `#search`: Enter selects the next hit in id order (`select(id, true)`: opens the panel and centres it); Shift+Enter the previous; the index wraps and resets when the query changes. Escape clears the query (and item 10's Escape does not close the panel while the search box has text).
- Expansion caused by search persists in `localStorage` like any other expansion (decision: same as clicking a reference in the panel).

Where: `applySearch` (line 977), `$('search').oninput` (line 1193), new `keydown` handler, HTML line 73.

Tests: `test_search_reveals_collapsed_and_counts` with `page_file`: click `#collapseAll`; fill `#search` with `"docs"`; wait 300 ms; `tasks().filter(n => !n.hasClass('dim')).map(n => n.id()) == ['4']`; `#searchCount` text is `"1 match"`; `expandedIds().has(1)` is true. Fill `"zzz"` → `"No matches"`. Fill `"e"` → press Enter → panel is displayed and `pinned` equals the first hit id; press Enter again → `pinned` advances. Clear → `#searchCount` is empty and no node has `.dim`.

Must not regress: `applySearch()` is still called at the end of `rebuild` and `applyData` so live refresh keeps the dimming; the `?types=` filter still constrains hits via `passes`.

### 5. H3: hover highlights without fading the plan

Problem: `mouseover` (line 1093) adds `.faded` (opacity 0.15) to everything outside the hovered neighbourhood, including Timeline names and lane headers, so on a projector any mouse movement blanks the slide.

Required behaviour:

- Hover: after a 120 ms delay (cancelled on `mouseout`), add `.hl` to the node and its predecessors and successors (`keep` as in `focusOn`, line 958). No `.faded` on hover. `#cy.title` tooltip unchanged.
- Click/pin (`select` → `refocus` → `focusOn`): fading remains but `.faded` opacity is 0.35. `.dim` (search) opacity is 0.2.
- `mouseout`: remove `.hl` from the hovered set, then `refocus()` so a pinned node keeps its highlight and fade.
- Split `focusOn(n, fade)`: hover calls `focusOn(n, false)`, `refocus` calls `focusOn(pinned, true)`.

Where: lines 957–968, 1093–1101, styles 333–334.

Tests: `test_hover_does_not_fade` with `page_file`, Graph: move the mouse to node `#5`'s rendered position, wait 200 ms; `cy.nodes('.faded').length == 0`; `cy.getElementById('5').hasClass('hl')` and `cy.getElementById('3').hasClass('hl')` (neighbour); move to `(5, 5)` inside `#cy` and wait 100 ms → no `.hl`. Click `#5` → `cy.nodes('.faded').length > 0` and the computed `opacity` of a faded node is 0.35.

Must not regress: `mirrorNames` still mirrors `.faded`/`.dim` onto Timeline name rows; pinned focus is unchanged in behaviour apart from opacity.

### 6. H4: empty and all-done states

Problem: an empty project, or a project where everything is done with Hide done on, renders a blank canvas with a full toolbar and legend (and in the Timeline a lone Today line).

Required behaviour:

- `<div id="empty" hidden><p id="emptyText"></p><button id="emptyAction" hidden></button></div>`, fixed, `top: var(--bar)`, `left: 0`, `right: var(--panel-w, 0px)`, `bottom: 0`, flex-centred, `pointer-events: none` on the wrapper and `auto` on the button, text 16 px `#e5e7eb`, button styled like `#panel button`.
- Evaluated at the end of `rebuild` and `applyData`, with `project = $('project').value` and `candidates = DATA.nodes.filter(n => !project || n.project === project)`:
  1. `tasks().length > 0` → hidden.
  2. `candidates.length === 0` → text `No tasks in <project> yet.` (or `No tasks yet.` when no project is selected); no button.
  3. Hide done is checked and every candidate has `derived_status === 'done'` → text `All <N> items are done.` (`All 1 item is done.` for one); button `Show done` → unchecks `#hideDone` and runs `rebuild()`.
  4. Otherwise → text `Nothing matches the current filters.`; button `Reset filters` → `types = new Set(TYPES)`, `$('search').value = ''`, `setGoal(null)` (which also syncs controls and the URL), then `rebuild()`.
- `layoutTimeline` adds no background elements (no Today pin, line, bands or grid) when there are no task rows.

Where: HTML after `#panel`; `rebuild` (line 848) and `applyData` (line 914); `layoutTimeline` early return.

Tests: new fixture `done_file`: milestone `Ship` due 2026-10-01 and task `Build` due 2026-09-20 with `dep add 1 2` then `done 2`. For each view: `tasks().length == 0`, `#empty` visible, `#emptyText == "All 2 items are done."`, `#emptyAction == "Show done"`; click it → `tasks().length == 2` and `#empty` hidden; in the Timeline before the click `cy.nodes('.bg').length == 0`. With `page_file` (which has no risk): select `#goal` = `"2"`, then click every type chip except `risk` off → `#emptyText == "Nothing matches the current filters."`; click `Reset filters` → all chips `.on`, `#goal` value `""`, `goal=` not in the URL, `tasks().length > 0`.

Must not regress: `test_page_renders_and_opens_panel` waits for `cy.nodes().length > 0`; keep that true for non-empty data. `toggleType` still refuses to turn off the last chip, so case 4 arises only via goal or search combinations and the risk-only case above.

### 7. M1: one date format

Problem: four formats on one screen: "15 Dec 2026" (labels, panel), "12/15" and "Today 10/14" (Timeline, goal picker), "2026-10-25" (conflict messages), "10/13/2026, 8:19:47 AM" (Created, Generated).

Required behaviour:

- `day(s)` for `YYYY-MM-DD`: `"14 Oct"` when the year equals `todayYear`, else `"15 Mar 2027"`. Non-matching strings are returned unchanged.
- Remove `md()`. `dateText` uses `day`: a point `"15 Dec"`; a span `"20 Oct–10 Nov"` (en dash, no spaces); across years `"15 Jan 2027–15 Mar 2027"`. Today pin: `"Today 14 Oct"`. Goal picker: `"#3 Pilot tenants migrated · 15 Dec"`. Month grid labels unchanged (`"Jan 2027"`).
- Conflict list items: `c.message.replace(/\d{4}-\d{2}-\d{2}/g, m => day(m))`.
- `fmt(iso)` (Created, Done, Generated): local date via `day()` plus local 24-hour time, `"13 Oct 08:19"`; a different year gives `"13 Oct 2025 08:19"`. Live stamp: `"Live · checked 09:41"` / `"Disconnected · tried 09:41"` using `toLocaleTimeString([], {hour: '2-digit', minute: '2-digit', hour12: false})`.

Where: `day` (line 132), `md` (line 625), `dateText` (line 636), `fillGoals` label (line 886), `tl:today` (line 783), `conflictList` (line 1018), `fmt` (line 991), `setStatus` (line 1230), `else` branch line 1260.

Tests: update `test_timeline_marks_baseline_and_today` to `"Today 13 Oct"`. New `test_date_format`: in `page_file`, `day('2026-10-30') == '30 Oct'`, `day('2027-03-15') == '15 Mar 2027'`; `cy.getElementById('3').data('label') == '20 Oct–25 Nov'` in the Timeline; `#goal` option text for value `"2"` is `"#2 Ship v1 · 1 Dec"`; after `select(3, false)` the panel text contains `"Baseline due"` and `"20 Nov (+5d) · plan"` and no `/\d{4}-\d{2}-\d{2}/` match.

Must not regress: `baselineText` already uses `day`; sorting in `fillGoals` and `cmp` uses raw ISO strings, not `day`.

### 8. M2: at risk and conflict as words; legible RAG stripe

Problem: in the Timeline, at risk (amber outline) and conflict (red outline) differ by colour only, and amber vs red contrast is 1.75:1. The lane stripe is 4 px wide and colour-only.

Required behaviour:

- `dateText` parts, in order: dates, rollup (`"1 of 4 done"`), `"Nd late"`, `"at risk"`, `"conflict"`, `"chase due"`, joined with `" · "`, each included under the same conditions as `labelOf` (line 442–445). Example: `"15 Oct–15 Nov · conflict"`, `"15 Dec · at risk"`.
- Stripe width 4 → 8 px, positioned at `x = 4` (both views).
- Band headers carry the word. Timeline head: `"App · RED"`, `"Data · GREEN"`. Swimlane `lane-bg` label: `clampLabel(name, LANE_W, 2) + '\n' + RAG` where `RAG` is `RED`/`AMBER`/`GREEN`. Header colour stays `#9ca3af`.
- Hues unchanged (`#ef4444`, `#f59e0b`, `#34d399`) so the page matches `report`.

Where: `dateText`; `stripe()`; `layoutLanes` band `name` (line 608); `layoutTimeline` head rows (line 759).

Tests: with `programme_file`, Timeline: `cy.getElementById('2').data('label') == '15 Dec · at risk'`; after `#expandAll`, node `6`'s label ends with `' · conflict'` and node `4`'s is `'20 Sep–10 Oct · 3d late'`; heads are `["Objectives · RED", "Data · AMBER", "Infra · RED", "Programme · RED", "Security · AMBER"]`; Swimlane: `cy.getElementById('lane:1').data('name')` ends with `'\nAMBER'`; `cy.nodes('.lane-rag')[0].width() == 8`.

Must not regress: item 1's band-head test strips the suffix after `" · "`; `test_lane_rag_stripes` reads `data('rag')`, unchanged.

### 9. M3: contrast tokens

Problem: computed WCAG ratios: stamp and panel "None" `#6b7280` on `#181c22` 3.54:1; search placeholder about 3.2:1; dependency edges `#3f4753` on `#111418` 1.97:1; part-of edges and Timeline bars `#4b5563` 2.4:1; blocked node background `#262c36` 1.32:1 and border `#343b47` 1.64:1 against the canvas, so the most common status is nearly invisible.

Required behaviour (exact values; ratios are against the named background):

| Token | Old | New | Ratio |
|---|---|---|---|
| `.stamp`, `#panel .none`, `#searchCount` colour | `#6b7280` | `#9ca3af` | 6.7:1 on `#181c22` |
| `#toolbar input::placeholder` (add rule, `opacity: 1`) | UA default | `#9ca3af` | 5.8:1 on `#232830` |
| edge `line-color`/`target-arrow-color` (line 274) | `#3f4753` | `#6b7280` | 3.8:1 on `#111418` |
| `edge.partof` colours (line 278) | `#4b5563` | `#6b7280` | 3.8:1 |
| `AXIS` (line 122; bars, grid, `tl-dep`, `mk-sum` remainder) | `#4b5563` | `#6b7280` | 3.7:1 on `#14181e` |
| `COLORS.blocked` | bg `#262c36`, fg `#9ca3af`, bd `#343b47` | bg `#2f3744`, fg `#d1d5db`, bd `#6b7280` | fg 8.0:1 on bg; bd 3.8:1 on canvas |
| `COLORS.done` | bg `#1d4ed8`, fg `#dbeafe`, op 0.75 | bg `#2563eb`, fg `#ffffff`, bd `#2563eb`, op 0.85 | fg 5.2:1; bg 3.5:1 on canvas |
| legend SVG fills `#262c36` (lines 88–95) | `#262c36` | `#2f3744` | matches node bg |
| `#panel li i` | no border | `border: 1px solid` the status `bd` colour | blocked dot visible |

Where: CSS lines 28, 46, 60; `COLORS` lines 110–115; `AXIS` line 122; styles 274–278; legend HTML; `refList` (line 1003).

Tests: `test_contrast_tokens` with `page_file`: `getComputedStyle($('stamp')).color == 'rgb(156, 163, 175)'`; `cy.getElementById('2')` (the blocked milestone) has `style('background-color') == 'rgb(47,55,68)'`; `cy.edges()[0].style('line-color') == 'rgb(107,114,128)'`. Add a pure-Python helper in the test that computes WCAG ratios for the table above and asserts each `>= 3.0` (non-text) or `>= 4.5` (text).

Must not regress: `badge()` and legend swatches derive from `COLORS`, so they update automatically.

### 10. M4: panel close button and Esc; focus-button wording per type

Problem: the panel closes only by clicking empty canvas; Esc does nothing; "Focus on this goal" appears on decisions, externals, issues and risks.

Required behaviour:

- `<button id="panelClose" aria-label="Close">×</button>` absolutely positioned at `top: 10px; right: 10px` inside `#panel` (`#panel { position: fixed }` already), 28×28 px, same colours as `#panel button`, `margin-top: 0`. Click → `closePanel()`. Rendered first in `openPanel`'s children.
- `document.addEventListener('keydown')`: on `Escape`, if `document.activeElement === $('search')` and its value is non-empty → clear the search (item 4); else if the panel is displayed → `closePanel()`.
- Focus button (`#focusGoal`, keep the id): milestone and objective → `Focus on this goal`; task, decision, external, issue → `Show only what this needs`; risk → the button is not rendered. When `goal === n.id` the text is `Show everything` for every type. `title` stays `Show only what this needs`.
- `--panel-w` on `:root` is `340px` while the panel is open and `0px` otherwise (used by items 6 and 11).

Where: `openPanel` (line 1024), `closePanel` (line 1076), line 1047.

Tests: `test_panel_close_and_esc` with `page_file`: `select(5, false)` → `#panelClose` visible; click it → `#panel` display `none` and `pinned == null`; `select(5, false)`; press `Escape` → closed. Wording: `select(2)` → `#focusGoal` text `Focus on this goal`; `select(3)` → `Show only what this needs`; with `raid_file`, `select(2)` (risk) → `#focusGoal` absent. `test_goal_focus_from_picker_and_panel` keeps passing (it only asserts `Show everything`).

Must not regress: tapping empty canvas still closes the panel; `cy.resize()` and the `fitView()` on first open are unchanged.

### 11. M5: legend default and size; hide unused rows

Problem: the legend is 510×133 px, open by default at every width, and `fitTarget` shrinks the plan to keep clear of it; "Baseline due" shows when no baseline exists.

Required behaviour:

- Layout: one wrapped strip. `#legend { left: 14px; bottom: 14px; max-width: calc(100vw - 28px - var(--panel-w, 0px)); padding: 4px 10px 6px; font-size: 12px; }`, `#legendBody { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 2px; }`, `#legend .col { display: contents; }`, `#legend .col div { margin: 0; gap: 6px; }`. Open height at 1440 is at most 64 px; closed at most 28 px.
- Default: when `store.get('taskgraph.legend')` is null, open if `window.innerWidth >= 1366`, else closed. A stored preference always wins.
- `syncLegend()` called from `syncControls`, `rebuild` and `applyData`: hide the `Baseline due` item unless `DATA.nodes.some(n => n.baseline && n.baseline.due)`; hide `Lane RAG` in the Graph view; hide the `Done` status item while `#hideDone` is checked.

Where: CSS lines 33–41; `setLegend` init (line 1211); new `syncLegend`.

Tests: update `test_legend_collapses_and_remembers`: replace `short < tall / 2` with `tall - short >= 20 and tall <= 64`. New `test_legend_defaults_and_rows`: at width 1280 with cleared storage the legend has class `closed`; at 1440 it does not; with `raid_file` (no baseline) the `Baseline due` item is hidden and with `page_file` it is shown; in `?view=graph` the `Lane RAG` item is hidden, in `?view=lanes` shown; `Done` is hidden until `#hideDone` is unchecked.

Must not regress: `fitTarget` reads the legend's live rect (line 821), so the reserve shrinks with the legend; `test_fit_keeps_nodes_clear_of_legend` unchanged.

### 12. M6: lanes-by-owner falls back to decider/party; Objectives band

Problem: with Lanes by owner, every milestone, decision and external lands in "Unassigned" because they carry `decider`/`party`, not `owner`. The objective sits in "Unassigned" in both views.

Required behaviour:

- `LANE_KEYS.owner = n => n.meta.owner ?? n.meta.decider ?? n.meta.party` (same precedence as `person()` in `tg.py`, line 174).
- `LANE_KEYS.lane = n => inheritedMeta(n, 'lane')`; `tag` and `project` unchanged.
- `laneOf` and band order as in Shared definitions (`Objectives` band for objectives without a value under the current key; sorted first).

Where: lines 153–158 and 475–478. Most of this lands in item 1; this item adds the owner fallback and asserts the band naming.

Tests: `test_lanes_by_owner_fallback` with `programme_file`, `?view=lanes&lanes=owner`: band names (before the RAG suffix) are `["ciso", "mei", "pd", "priya"]`; `#8 Residency` is in band `ciso`. With `?view=lanes` and `page_file`: first band is `Objectives` containing `#1 Launch`, and no band is named `Unassigned`.

Must not regress: `?lanes=` URL param and the `taskgraph.lanes` store key; `laneOf` is used by `bandRag`, so stripes follow the chosen key.

### 13. M7: re-fit after Expand all and Collapse all

Problem: both buttons call `rebuild(true)`, which keeps the viewport, so Collapse all leaves five nodes in the top third of the screen and Expand all on a big plan drops below the readable zoom.

Required behaviour: `#expandAll` and `#collapseAll` call `rebuild()` (full re-layout and `fitView()`, which applies item 2's floor) and then reopen the pinned panel as now. Double-click `toggleExpand` keeps `rebuild(true)` so a single toggle does not jump the view.

Where: lines 1194–1203.

Tests: `test_expand_collapse_refit` with `page_file`, Graph at 1400×900: `page.click('#collapseAll')` → every task node's rendered bbox is inside `#cy` and `abs(cy.zoom() - fitTarget().zoom) < 1e-6` (small plan, above the floor); with `tall_file`, `#expandAll` then `#collapseAll` → `cy.zoom()` equals `max(READABLE, fitTarget().zoom)` within `1e-6`.

Must not regress: `covered()`/`fitIfOutside` after a double-click toggle; `applyData` flash of new nodes.

## Deferred (not in this release)

- L1 ARIA: `aria-label` on the four selects and the search input, `aria-pressed` on type chips, `aria-expanded` on the legend toggle, `role="img"` with a summary on `#cy`, a visually hidden list of late and at-risk items.
- L2 Timeline conflict-edge routing loops and doubled arrowheads.
- L3 Swimlane edge visibility beyond item 9's colour change.
- L4 Export: `cy.png({full: true, scale: 2, bg: '#111418'})` behind an Export PNG button and a print stylesheet.
- L5 A caption stating the Graph's bottom-to-top flow, or an LR layout on wide screens.

## Implementation order and commits

One commit per item, in scope order 1 to 13, each with its tests green (`python3 -m pytest plugins/taskgraph/skills/taskgraph/tests/test_page.py`). Commit 14: version bump and SKILL.md wording. Items 1 and 12 share `laneOf`; implement the Shared definitions in commit 1 and leave only the owner fallback and its test for commit 12.

## Version bump

Set `"version": "1.9.0"` in: the `taskgraph` entry of `plugins[]` in `.claude-plugin/marketplace.json` (line 84), `plugins/taskgraph/.claude-plugin/plugin.json`, `plugins/taskgraph/openclaw.plugin.json`.

## SKILL.md wording

- Weekly steering prep, step 5, replace the last sentence ("Milestones are listed first in each lane, and each lane header carries a red, amber or green stripe from the same rules as `report`.") with: "Rows are grouped by lane in both the Swimlane and the Timeline; a child nests under its parent only when both are in the same lane, and objectives sit in an Objectives band at the top. Milestones are listed first in each lane. Each lane header carries a red, amber or green stripe and the word RED, AMBER or GREEN, from the same rules as `report`, over every open item in that lane whatever is expanded. Search finds items inside collapsed summaries and expands them; Enter steps through the matches. Dates on the page read `14 Oct`, with the year only when it is not this year."
- Rules, the `lane` meta key: change "(the workstream; groups rows in the Swimlane view)" to "(the workstream; groups rows in the Swimlane and Timeline views)".
- The "Will we hit it?" paragraph's "the graph outlines them in amber" becomes "the graph outlines them in amber and labels them `at risk`".

## Decisions recorded

1. Lane inheritance is computed in the page (`inheritedMeta`), not by adding `lane` to `NODE_FIELDS`, to avoid a `tg.py` change.
2. Stripes ignore the type filter and expansion but respect the goal, project and Hide done, so a goal-focused page reports RAG for the focused scope.
3. One readability floor (0.9) for all views; Graph anchors on the goal/objective, the other views on the plan's top-left corner.
4. The toolbar wraps rather than collapsing into a menu; two rows at laptop widths is accepted.
5. Search expansion persists like any other expansion; Enter opens the panel as well as centring.
6. Hover never fades; click fades at 0.35.
7. "Reset filters" clears types, search and goal, but not the project or Hide done.
8. Years are omitted when they match the current year everywhere, including Created/Done rows.
9. RAG hues are unchanged; the word on the header is the colour-independent channel.
10. Blocked nodes get a lighter background rather than a lighter border alone, so Ready, In progress and Blocked remain three distinct fills.
11. The legend becomes one wrapped strip; the existing "collapse halves the height" test is relaxed to "collapse removes at least 20 px".
12. Objectives without a lane form an `Objectives` band in both views; with another lane key an objective that has a value under that key goes with it.
13. Expand all and Collapse all refit; double-click does not.
