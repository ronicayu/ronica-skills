// Overview of Lifecycle.tla for the README: the main flow in about a dozen states.
// Use it with overview.cfg (FULL_ENV = FALSE, OPERATOR_PAUSES = TRUE).
// Labels are for the product reader (statechart SKILL.md, "Pick the chart"): each state names its subject, each arrow
// starts with its actor, and `glossary` explains every actor and short noun. The actors have the names of view.mjs.

export const title = "Task attempt lifecycle (agentic-team 0.19.0)";

// Closed: a passing close happened (Lifecycle.tla `Closed`). Since 0.19.0 the task stays in progress until the merge.
const closed = (v) => v.verdict === "artifact-verified";

const WORKING = "Task session working";

export const state = (v) => {
  if (v.abandoned) return "Task abandoned";
  if (v.merged) return "Task merged";
  if (closed(v)) return "Task closed, waiting for the merge";
  if (v.status === "open") return "Task not started";
  if (v.lastTask === "STOPPED" || v.lastTask === "STOPPEDhead") return "Task paused";
  // The same words as the section of run.py status.
  if (v.verdict !== "none") return "Verdict recorded, not closed";
  if (v.verifier !== "none") {
    if (v.vv !== "none") return "Verifier session filed its verdict";
    if (v.verifier === "busy") return "Verifier session working";
    return "Verifier session gone, no verdict";
  }
  if (v.lastTask === "none") return v.worker === "finished" ? "Task session gone, no report" : WORKING;
  if (v.lastTask === "DIED") return "Attempt marked DIED, no report";
  if (v.lastTask === "PASS") return "Task session reported PASS";
  return "Task session reported ISSUES or BLOCKED";
};

const recordLabel = (from, to) => {
  if (to.merged && !from.merged) return "the Manager's record finds the task merged";
  if (to.lastTask === "DIED" && from.lastTask !== "DIED") return "the Manager's record marks the attempt DIED";
  if (to.lastTask === "STOPPEDhead" && from.lastTask !== "STOPPEDhead") return "the Manager's record commits the WIP";
  return "the Manager runs record";
};

// A close from one state ends in one of three states; the condition tells the arrows apart. A failing and a
// check-only verdict share one condition, because they go to one state.
const closeLabel = (from, to) => {
  if (!closed(to)) return "the Manager closes the task [verdict does not pass]";
  if (to.merged && !from.merged) return "the Manager closes the task [verdict passes, merged at once]";
  return "the Manager closes the task [verdict passes, the merge waits]";
};

const HOST_SAYS = {
  clean: "ready to merge",
  behind: "behind the target branch",
  blocked: "blocked by a check",
  dirty: "in conflict",
};

export const step = (action, from, to) => {
  switch (action) {
    case "Launch": return from.attempt === 0 ? "the Manager starts the first attempt" : "the Manager starts the next attempt";
    case "VerifyPlain": case "VerifyAgain": return "the Manager starts a verifier session";
    case "CloseAuto": case "CloseManual": return closeLabel(from, to);
    // The README chart draws the pause only from the working state, where it normally happens. A pause from a
    // verifying or verdict state also leads to "Task paused"; hiding those arrows keeps the chart readable.
    case "Stop":
      if (state(from) !== WORKING) return null;
      return from.worker === "busy" ? "the operator pauses the task session"
        : "the Manager stops the idle task session, as record says";
    case "LaunchStopsIdleThenRefuses": return "the Manager tries to start an attempt: the idle session stops, and the start is refused";
    case "Abandon": return "the Manager abandons the task";
    case "Record": return recordLabel(from, to);
    case "Done": return "the Manager has nothing more to do";
    case "WorkerEnds": return "the task session ends without a report";
    case "WorkerExits": return "the stopped task session exits";
    case "WorkerFilesPass": return "the task session reports PASS";
    // One label for both: they go to one state, so the command does not join two labels with "or".
    case "WorkerFilesIssues": case "WorkerFilesBlocked": return "the task session reports ISSUES or BLOCKED";
    case "VerifierEnds": return "the verifier session ends without a verdict";
    // One label for the three verdicts: they go to one state, and the close arrows out of it name the verdict.
    case "VerifierFiles": return "the verifier session files its verdict";
    case "OperatorOrdersStop": return "the operator writes a STOP order";
    case "OperatorLiftsStop": return "the operator lifts the STOP order";
    case "OperatorMerges": return "the operator merges the branch by hand";
    case "HostDecides": return `the code host marks the request ${HOST_SAYS[to.pr]}`;
    case "TargetMoves": return "another task or a reviewer moves the target branch on";
    case "CheckFails": return "the code host reports a failing check";
    case "CheckPasses": return "the code host reports all checks passing";
    case "SomeoneMerges": return "a reviewer merges the request on the code host";
    case "SomeoneCloses": return "a reviewer closes the request on the code host";
    case "SomeoneReopens": return "a reviewer reopens the request on the code host";
    default: return action;
  }
};

export const group = (v) => {
  if (v.abandoned || v.merged) return "End";
  if (closed(v)) return "Closing";
  if (v.status === "open") return "Start";
  if (v.verdict !== "none") return "Verdict";
  if (v.verifier !== "none") return "Verifying";
  return "Working";
};

export const colors = {
  Start: "blue",
  Working: "orange",
  Verifying: "purple",
  Verdict: "yellow",
  Closing: "teal",
  End: "tan",
};

// The same words as view.mjs, for the terms this chart uses.
export const glossary = {
  "the Manager": "The Claude session that runs the team: it runs run.py's commands (launch, verify, close, abandon, record) and follows the next step that record prints.",
  "the operator": "The person who owns the run: writes the standing orders, pauses work, repairs files and, in local mode, merges by hand.",
  "the task session": "The Claude session that does one attempt of the task in its own worktree and files one report.",
  "the verifier session": "The Claude session that checks the task session's work and files one verdict.",
  "record": "run.py record, the Manager's check of every task: it reads the sessions and the result rows, writes what it finds, and prints the next step.",
  "the code host": "The service that holds the request, such as GitHub, when the team merges through requests.",
  "a reviewer": "A person who acts on the request on the code host, the operator included.",
  "another task": "Another task of the same run, whose merge moves the target branch on.",
  "attempt": "One run of a task session on the task; after the last one allowed (3 in run.py; a model config can set fewer), the Manager abandons the task.",
  "report": "The task session's result row: PASS, ISSUES or BLOCKED.",
  "PASS": "The task session says the work is done and checked.",
  "ISSUES": "The task session says the work is done but has problems that need another attempt.",
  "BLOCKED": "The work cannot go on without a decision; the task session or the Manager files it.",
  "DIED": "The row that record files when a task session ended without a report.",
  "verdict": "The verifier session's finding: passes, check-only or fails. Only a passing verdict lets the task merge.",
  "WIP": "Work in progress: the task session's changes that are not committed yet when it pauses or stops.",
  "STOP order": "The operator's standing order that pauses new attempts and merges until the operator lifts it.",
  "idle session": "A task or verifier session that has filed its result and waits; the next attempt stops it.",
  "request": "The pull request or merge request for the task's branch on the code host.",
  "merged at once": "The close merges the branch, or records the task as merged because the branch has no commit to merge.",
};
