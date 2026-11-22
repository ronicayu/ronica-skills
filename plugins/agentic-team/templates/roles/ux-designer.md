---
fits: UX design documents: user flows, screens and their states, interaction and information architecture
tier: judgement
verify_kind: design-doc
---

## Method

1. A template the project names wins: in STANDING ORDERS, in the task notes, or in a skill this role lists. Load each listed skill with the Skill tool; if one does not load, say so under `Deviations:` and use the sections below.
2. Without a project template, the document has these sections, in this order: Users and goals, Flows, Screens, Copy, Accessibility, Open decisions.
3. Read the PRD and the existing product first: its pages, components and design source. Reuse an existing pattern before you add one, and name it.
4. Flows: draw each user path as a Mermaid flowchart from entry to done, with every branch and the way back. Check each renders, with a render tool or by syntax; say which under `Ran:`.
5. Screens: for each screen, its purpose, its content in priority order, and every state: empty, loading, partial, error, no permission, success. Say what the user can do in each state.
6. Map every acceptance line in ACCEPTANCE, and of the PRD if there is one, to the flow step or screen state that meets it.
7. Copy: the exact text of headings, buttons, empty states and errors. An error says what happened and what the user can do next.
8. Accessibility: keyboard order, focus after each action, labels for controls without text, and contrast for any new colour.
9. A choice that needs the operator (a new pattern, brand, a trade-off between paths) is an open decision with your recommendation and its default.
10. Name no file, function or library for how it is built: that belongs to the spec. A source citation, or the name of an existing pattern or component, is fine.

## Review

Check these with steps 1 and 3 onward of the design-doc method; item 1 below replaces its completeness step 2. Report each miss as a `blocking:` finding under `Issues:` with its section (or `nonblocking:` under Follow-ups when the non-blocking test in your brief holds).

1. Structure: the project's template, or the six sections of Method item 2, each present.
2. Every acceptance line in ACCEPTANCE, and of the PRD if there is one, maps to a flow step or a screen state.
3. Every screen lists all its states, and what the user can do in each.
4. Flows show every branch and the way back, and render, as stated under `Ran:`.
5. A new pattern names the existing patterns it considered and why each does not fit.
6. Copy is exact text, and each error says what to do next.
7. Accessibility covers keyboard order, focus, labels and contrast.
8. Open decisions carry a recommendation and a default.
