// Phase view of Lifecycle.tla (agentic-team 0.19.0, #99): each state is the phase meta that run.py would derive for
// it, and each step is labelled with the event of run.py's TRANSITIONS that makes it. phase-edges.mjs reads TLC's state
// graph through this view and writes phase-edges.json, which tests/test_run.py checks against TRANSITIONS.
// A step that keeps the phase is a self-loop: the chart and phase-edges.mjs drop it.

// The labels are run.py's phase and event names, not the product words of view.mjs: phase-edges.json and the test
// compare them with TRANSITIONS, so do not change them. `glossary` gives each name in product words (#108).
export const title = "Task phases that run.py records, and the events that move them (agentic-team 0.19.0)";

export const glossary = {
  // The phases (state labels).
  "none": "Phase: the task is not started; no attempt has been launched.",
  "running": "Phase: the task session is working on the attempt and has filed no report yet.",
  "reported": "Phase: the task session filed its report (PASS, ISSUES or BLOCKED); no verifier session runs yet.",
  "verifying": "Phase: a verifier session checks the task session's PASS, or has filed a verdict that the Manager has not closed on.",
  // "stopped" and "merged" are a phase and an event, so each has one entry for both.
  "stopped": "Phase: the attempt ended without a report: the task session was paused or stopped, or record marked it DIED or BLOCKED. Event: the operator pauses the task session, or the Manager or its record stops an idle or stuck one.",
  "verdict_failed": "Phase: the Manager recorded a verdict that does not pass (fails or check-only); the task is not closed.",
  "awaiting_merge": "Phase: the Manager closed the task on a passing verdict; the branch waits for its merge.",
  "merged": "Phase: the task's branch is merged and the task is done. Event: the Manager's record, or a later close, records the merge.",
  "abandoned": "Phase: the Manager abandoned the task.",
  // The events (arrow labels).
  "launch": "Event: the Manager starts an attempt, and the task session starts work.",
  "verify": "Event: the Manager starts a verifier session.",
  "close_failed": "Event: the Manager closes the task on a verdict that does not pass; the verdict is recorded and the task stays open.",
  "close_waits": "Event: the Manager closes the task on a passing verdict; the merge has not happened yet.",
  "close_waits, merged": "Event: the Manager closes the task on a passing verdict and the branch merges in the same step (two writes of run.py).",
  "died": "Event: the Manager's record marks the attempt DIED: the task session ended without a report.",
  "abandon": "Event: the Manager abandons the task.",
  "record": "Event: any other write of the Manager's record; it never moves the phase.",
  "done": "Event: the task has ended; the Manager has nothing more to do.",
  "seen_<phase>": "Event: a session, the code host or the operator changed something, and the Manager's next record sees the new phase, such as seen_reported when the task session files its report.",
  // The actors that the descriptions name.
  "the Manager": "The Claude session that runs the team with run.py's commands.",
  "the Manager's record": "run.py record, the Manager's check of every task: it reads the sessions and the result rows, writes what it finds, and prints the next step.",
  "the operator": "The person who owns the run.",
  "the task session": "The Claude session that does one attempt of the task and files one report.",
  "the verifier session": "The Claude session that checks the task session's work and files one verdict.",
};

// Lifecycle.tla `Phase`, the model's reading of derive_phase. Change the two together. "none" is the code's None.
const WORKER_RESULTS = ["PASS", "ISSUES", "BLOCKED"];
export const state = (v) => {
  if (v.abandoned) return "abandoned";
  if (v.merged) return "merged";
  if (v.status === "done") return "awaiting_merge";
  if (v.status === "open") return "none";
  if (v.verdict !== "none") return v.verdict === "artifact-verified" ? "awaiting_merge" : "verdict_failed";
  if (v.lastTask === "none") return "running";
  if (!WORKER_RESULTS.includes(v.lastTask)) return "stopped";
  if (v.verifier !== "none" || v.vv !== "none" || v.vManager !== "none") return "verifying";
  return "reported";
};

// The event names are run.py's (the comment above TRANSITIONS). One model step that run.py makes in two writes gets
// both events, joined by ", ": a passing close that merges at once writes close_waits, then mark_merged writes merged.
export const step = (action, from, to) => {
  const before = state(from);
  const after = state(to);
  switch (action) {
    case "Launch": case "LaunchStopsIdleThenRefuses": return "launch";
    case "VerifyPlain": case "VerifyAgain": return "verify";
    case "CloseAuto": case "CloseManual":
      if (after === "verdict_failed") return "close_failed";
      if (before === "awaiting_merge") return "merged"; // resume_close: the merge is recorded (mark_merged)
      return after === "merged" ? "close_waits, merged" : "close_waits";
    case "Stop": return "stopped";
    case "Abandon": return "abandon";
    case "Merged": return "merged";
    case "Record":
      if (to.merged && !from.merged) return "merged"; // mark_merged
      if (to.lastTask === "DIED" && from.lastTask !== "DIED") return "died";
      if (to.lastTask === "BLOCKEDmgr" && from.lastTask !== "BLOCKEDmgr") return "stopped"; // file_stuck
      return "record"; // no other write of record moves the phase; the test fails on this name if one does
    case "Done": return "done";
    // The world moved (a session, the host, the operator): the next record's settle_phase sees the rows say `after`.
    default: return `seen_${after}`;
  }
};
