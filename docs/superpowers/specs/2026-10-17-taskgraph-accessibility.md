# Accessibility Audit: taskgraph graph page (1.13.0)
**Standard:** WCAG 2.1 AA | **Date:** 2026-10-17

Method: an axe-core 4.10 scan in eight states (Graph, Graph with panel, Timeline, Load, and each popover open), keyboard-only walkthrough, the accessibility tree from Chromium, and contrast computed from the CSS tokens. Screen-reader testing on VoiceOver or NVDA is still to be done by a person.

### Summary
**Issues found:** 21 | **Critical:** 3 | **Major:** 10 | **Minor:** 8

### Findings

#### Perceivable
| # | Issue | WCAG Criterion | Severity | Recommendation |
|---|-------|---------------|----------|----------------|
| P1 | The plan is drawn on a canvas: items, their status and their links are invisible to a screen reader. | 1.1.1 Non-text content | 🔴 Critical | Give the canvas a name and a summary, and announce each item (title, status, dates, owner, flags) as keyboard focus reaches it. |
| P2 | Ready, In progress, Blocked and Done differ only by fill colour, on nodes, Timeline bars, panel rows and search results. | 1.4.1 Use of color | 🟡 Major | Add a status mark that differs in shape: ✓ done, ◔ in progress, ⊘ blocked (none on nodes for ready, ○ in lists), shown in the legend. |
| P3 | Control borders (`#343a45` on `#181c22`) are 1.5:1, so text boxes and selects have no visible edge. | 1.4.11 Non-text contrast | 🟡 Major | Borders `#6b7280` (3.5:1). |
| P4 | View options greys groups that do not apply with `opacity: .5`: text falls to 2.7:1 while the radios still work. | 1.4.3 Contrast | 🟡 Major | Keep full contrast, disable the inputs, and say "Timeline only" in the heading. |
| P5 | No landmarks or headings: no `main`, no `h1`, toolbar, legend and panel are plain `div`s. | 1.3.1 Info and relationships | 🟡 Major | `header`, `main`, `aside` (panel), a labelled `section` for the legend, and a visually hidden `h1` naming the plan. |
| P6 | Load table: row names are `td`, no caption, column headers have no scope. | 1.3.1 Info and relationships | 🟢 Minor | Row headers as `th scope="row"`, `scope="col"` on week headers, a caption. |
| P7 | Filter popover groups and View options radios have no group name. | 1.3.1 Info and relationships | 🟢 Minor | `role="group"` / `role="radiogroup"` labelled by the group heading. |
| P8 | The custom tooltip cannot be dismissed without moving the pointer. | 1.4.13 Content on hover | 🟢 Minor | Esc hides it. |

#### Operable
| # | Issue | WCAG Criterion | Severity | Recommendation |
|---|-------|---------------|----------|----------------|
| O1 | Nodes cannot be reached or opened with the keyboard. | 2.1.1 Keyboard | 🔴 Critical | Make the canvas one tab stop: arrows move between items (Timeline steps by row), Enter opens the panel, Space expands or collapses a summary, + and − zoom, Home and End jump. A clear focus ring on the current item. |
| O2 | Panel rows (blocks, blocked by, chain, conflicts, children), Load cells and the Load item lists are clickable `li`/`td` elements with no tab stop. | 2.1.1 Keyboard | 🔴 Critical | Focusable `role="button"` with Enter and Space. |
| O3 | The panel's resize edge works only with a mouse. | 2.1.1 Keyboard | 🟡 Major | A focusable separator; arrows resize it. |
| O4 | Opening the panel from the keyboard leaves focus where it was; closing it drops focus to the page. When the panel redraws (refresh, following a row) the focused row is destroyed and focus is lost. | 2.4.3 Focus order | 🟡 Major | Move focus to the panel title when opened from the keyboard, return it to where it came from on close, and restore it after a redraw. |
| O5 | Esc closes a popover but focus stays on a control that is no longer visible. | 2.4.3 Focus order | 🟡 Major | Return focus to the popover's button. |
| O6 | Focus rings are the browser default, hard to see on some dark fills. | 2.4.7 Focus visible | 🟢 Minor | One `:focus-visible` ring, `#93c5fd`, 2 px. |
| O7 | No way to skip the two toolbar rows. | 2.4.1 Bypass blocks | 🟢 Minor | A "Skip to the plan" link that appears on focus. |
| O8 | Chip ×, search × and the legend toggle are about 16 px targets. | 2.5.5 Target size (AAA) / 2.5.8 (2.2 AA) | 🟢 Minor | At least 24 × 24 px. |
| O9 | Panning animations ignore the reduced-motion setting. | 2.3.3 (AAA) | 🟢 Minor | No animation when `prefers-reduced-motion: reduce`. |

#### Understandable
| # | Issue | WCAG Criterion | Severity | Recommendation |
|---|-------|---------------|----------|----------------|
| U1 | Project, goal and search are named only by `title` (axe: label-title-only). | 3.3.2 Labels or instructions | 🟡 Major | `aria-label` on each; the placeholder already shows the purpose. |

#### Robust
| # | Issue | WCAG Criterion | Severity | Recommendation |
|---|-------|---------------|----------|----------------|
| R1 | Goal and search comboboxes never set `aria-activedescendant`, so arrowing through options is silent; options have no ids or selected state. | 4.1.2 Name, role, value | 🟡 Major | Option ids, `aria-selected`, `aria-activedescendant`, `aria-autocomplete="list"`. |
| R2 | The view buttons do not say which one is current; popover buttons claim `aria-haspopup` (a menu) but are disclosures; ⚙ has no name. | 4.1.2 Name, role, value | 🟡 Major | `aria-pressed` on view buttons, `aria-controls` + `aria-expanded` on disclosures, `aria-label="View options"`. |
| R3 | Changes that happen away from focus are silent: filter results, "Copied", the empty state, the disconnected banner. | 4.1.3 Status messages | 🟢 Minor | A polite live region for counts and confirmations; `role="status"` on the empty state, `role="alert"` on the banner. |

### Color Contrast Check
| Element | Foreground | Background | Ratio | Required | Pass? |
|---------|-----------|------------|-------|----------|-------|
| Body and panel text | #e5e7eb | #181c22 | 13.9:1 | 4.5:1 | ✅ |
| Muted text (stamp, notes, counts) | #9ca3af | #181c22 | 6.7:1 | 4.5:1 | ✅ |
| Links, focus ring | #93c5fd | #181c22 | 9.5:1 | 4.5:1 / 3:1 | ✅ |
| Chip text | #e5e7eb | #2b3442 | 10.1:1 | 4.5:1 | ✅ |
| Greyed View options group | #5a6069 | #181c22 | 2.7:1 | 4.5:1 | ❌ → fixed |
| Control borders | #343a45 | #181c22 | 1.5:1 | 3:1 | ❌ → #6b7280, 3.5:1 |
| Timeline labels | #9ca3af | #14181e | 7.0:1 | 4.5:1 | ✅ |
| Banner | #1c1004 | #f59e0b | 8.7:1 | 4.5:1 | ✅ |
| Load cell ink (each bucket) | see Load view | | ≥ 4.6:1 | 4.5:1 | ✅ |

### Keyboard Navigation (after the fixes)
| Element | Tab Order | Enter/Space | Escape | Arrow Keys |
|---------|-----------|-------------|--------|------------|
| Skip link | 1 | Jumps to the plan | — | — |
| Toolbar controls | 2… in reading order | Activate | Closes the open popover, focus back on its button | Goal and search lists: move the option |
| Plan canvas | After the toolbar | Enter opens the panel; Space expands or collapses | Closes the panel | Move between items; Home and End; + and − zoom |
| Load cells | One stop per cell | List the items in that cell | Closes the panel | — |
| Panel | After the plan | Rows open the item they name | Closes the panel, focus returns | Resize edge: ← wider, → narrower |

### Screen Reader
| Element | Announced As | Issue |
|---------|-------------|-------|
| Canvas | "Plan, 15 items. Arrow keys move between items…" | Was unnamed |
| Focused item | "#17 Cut over pilot tenants. Blocked. Due 19 Dec. Owner Tom. Conflict. Enter for details." | Was silent |
| View buttons | "Timeline, toggle button, pressed" | Pressed state was missing |
| Filter result | "12 items shown" | Was silent |

### Priority Fixes
1. **Keyboard and screen-reader access to the plan (O1, O2, P1).** Without these, a keyboard or screen-reader user cannot use the page at all.
2. **Status not by colour alone (P2) and visible control edges (P3, P4).** These help colour-blind and low-vision users, and anyone on a projector.
3. **Focus management and names (O3–O5, U1, R1, R2, P5).** Each lets a keyboard user complete a task without getting lost.
4. **Polish (P6–P8, O6–O9, R3).**

### Status after the fixes
All 21 findings are fixed in the same change. The axe-core 4.10 scan (WCAG 2.0/2.1 A and AA plus best practice) reports 0 violations in every state above. Two checks stay "incomplete", which means axe could not decide:
- contrast of the status glyphs, which axe cannot measure; checked by hand at 6.6:1 or better;
- the legend toggle sitting over the canvas.

At 200% zoom (640 px wide) nothing scrolls sideways, and the panel never exceeds the viewport. Page tests cover each behaviour: keyboard path, Timeline row steps, panel buttons and focus restore, names and states, Load cells, and reduced motion.

Still for a person to do: a pass with VoiceOver and NVDA to hear how each item is announced. The text is set in `describe()`; adjust there.
