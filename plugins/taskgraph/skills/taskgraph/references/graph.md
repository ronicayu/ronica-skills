# Taskgraph graph guide

Run `graph` to write and open the interactive plan. Run `serve` to serve all projects live; the page refreshes when the database changes. Add `?project=NAME` to the URL to select a project. Taskgraph reuses one server per database.

## Views and navigation

The page has Graph, Swimlane, Timeline, and Load views. The first toolbar row contains the project, goal, view, view options, search, and live status. The second row contains filters, removable filter chips, Fit, and More actions: Expand all, Collapse all, Re-layout, Export PNG, Print, Refresh now, and Copy link to view.

Use View options to set lane grouping, show or hide the legend, choose which dependencies appear in the Timeline, and set the theme. The Timeline shows conflicts only by default. You can also show the critical path or all dependencies. Add `?deps=critical` to the URL to show the critical path. Set the theme to Auto, Light, or Dark. Add `?theme=light` to open the page in light theme. Taskgraph remembers each browser's theme setting.

Use the goal box or **Focus on this goal** in a node panel to focus on a milestone or objective. All views then show the work that goal needs: dependencies, completed work, summary children on the path, inherited dependencies, and risks that point to any of those items. The view shows done/total and outlook. Share the focused goal by adding `?goal=ID` to the URL:

```text
http://127.0.0.1:7777/?project=NAME&goal=ID
```

You can filter by status (done is hidden by default), flags (late, at risk, conflict, chase due), type, owner (including decider or party), and inherited lane. A summary stays visible if anything inside it matches. The URL stores filters in comma-separated `status=`, `flag=`, `types=`, `owner=`, and `lane=` parameters. For example: `?project=NAME&owner=Tom&flag=late,atrisk`. Add `?task=ID` to open an item's panel. Taskgraph will relax any filter that hides that item.

Press `/` to focus Search. Search matches titles, exact `#id`, owner, decider, party, contact, lane, team, tags, and notes. Use the arrow keys, Enter, or a click to open a result. Enter moves through results. Search expands collapsed summaries to show matches, then folds them again. Search also reports when a filter hides a match.

Keyboard controls: Press **F** to fit the view, **E** to expand all, and **C** to collapse all. Press **Esc** to clear a focused search box, close an open menu, or close the panel. Browser Back and Forward move through views, goals, and projects. Hover over a dependency to see who waits for whom and the conflict gap. Click it to open the late item. A chase-due external names the party to chase.

## Items, lanes, and accessibility

The panel shows the owner, dates, baseline drift, lane, estimate, reasons for red or at-risk status, dependencies, driving chain, parent, children, and notes. Find the type, project, and other metadata under Details. Notes support Markdown headings, emphasis, lists, checklists, quotes, code, tables, and HTTP(S)/mailto links. HTML appears as text. Following a row adds a back step (Alt+Left). Select **Copy link** to copy the item URL. Drag the panel's left edge to resize it.

Swimlane and Timeline group rows by lane. A child nests under its parent only if both use the same lane. Objectives appear in their own band. Milestones appear first in each lane. Lane headers show RED, AMBER, or GREEN, using the same rules as `report`. The colour reflects all open items in the lane. A collapsed summary reports how much late or conflicting work it hides.

The page supports keyboard and screen-reader use. Press Tab to reach **Skip to the plan**, then move through each control. The plan is one tab stop. Use the arrow keys to move between items (by row in Timeline), Home and End to jump, Enter to open a panel, Esc to return focus, Space to expand or collapse a summary, and plus/minus to zoom. Screen readers can read each item's status, dates, owner, and flags. Status uses text or a shape as well as colour: ✓ done, ◔ in progress, ⊘ blocked, and ○ ready in lists. Panel rows and Load cells are buttons. Use the arrow keys to resize the panel edge. The page respects reduced-motion settings.

The page opens at a readable zoom and scrolls large plans. Fit shows the whole plan. Clicking an item keeps it visible beside the panel. For plans over 250 items, Graph uses a faster layout and reuses layouts it has already computed.

## Export and print

Select **Export PNG** to save the full filtered view, not just the visible area. The image uses 2× resolution and includes a title bar with the project, goal, view, date, active filters, and legend. Select **Print**, or use the browser's Print / Save as PDF, to create a landscape page in light theme. The printout includes the title, filters, whole plan, legend, and the open item's panel on a second page. Dates appear as `14 Oct`; Taskgraph shows the year only when it is not the current year.
