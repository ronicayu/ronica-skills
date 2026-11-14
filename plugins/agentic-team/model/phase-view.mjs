// Phase view of Lifecycle.tla (agentic-team 0.19.0, #99): each state is the phase meta that run.py would derive for
// it, and each step is labelled with the event of run.py's TRANSITIONS that makes it. phase-edges.mjs reads TLC's state
// graph through this view and writes phase-edges.json, which tests/test_run.py checks against TRANSITIONS.
// A step that keeps the phase is a self-loop: the chart and phase-edges.mjs drop it.

export const title = "Task phases (agentic-team 0.19.0)";

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
