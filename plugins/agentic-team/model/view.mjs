// Full view of Lifecycle.tla (agentic-team 0.19.0): every state the Manager can tell apart in `record` and `status`.
// Labels are for the product reader (statechart SKILL.md, "Pick the chart"): each state names its subject, each arrow
// starts with its actor, and `glossary` explains every actor and short noun. One name per actor, in every label.

export const title = "Task attempt lifecycle (agentic-team 0.19.0)";

const LEVEL = {
  "artifact-verified": "passes",
  "check-only": "check-only",
  "verify-failed": "fails",
};
// The verdict as an adjective, for the state labels.
const VERDICT = {
  "artifact-verified": "Passing",
  "check-only": "Check-only",
  "verify-failed": "Failing",
};
// Closed: a passing close happened (Lifecycle.tla `Closed`). Since 0.19.0 the task stays in progress until the merge.
const closed = (v) => v.verdict === "artifact-verified";
const STUCK = ["idleBlocked", "prompt"];
const IDLE = ["idle", "idleQuiet"];

const sessionNote = (who, s) => {
  if (s === "idleBlocked") return `, ${who} asked a question`;
  if (s === "prompt") return `, ${who} on a prompt`;
  if (IDLE.includes(s)) return `, ${who} idle`;
  if (s === "failed") return `, ${who} failed`;
  if (s === "ghost" || s === "ghostStopped") return `, ${who} is a ghost row`;
  if (s === "ghostGone") return `, ${who} is a ghost row gone quiet`;
  return "";
};

// The request as the closed states name it, and as the close arrows name it in their condition.
const REQUEST = {
  none: "branch waits for the merge",
  closed: "request closed unmerged",
  dirty: "request conflicts",
  behind: "request behind",
};
const requestWords = (pr) => REQUEST[pr] ?? "request open";

export const state = (v) => {
  if (v.abandoned) return "Task abandoned";
  if (v.merged) return "Task merged";
  if (closed(v)) return `Task closed, ${requestWords(v.pr)}`;
  if (v.status === "open") return "Task not started";
  if (v.lastTask === "STOPPED") return v.stopReason === "pause" ? "Task paused, WIP not committed yet" : "Task stopped, WIP not committed yet";
  const faultNote = v.fault === "role" ? ", role file broken" : v.fault === "exclude" ? ", info/exclude read-only" : "";
  if (v.verdict !== "none") return `${VERDICT[v.verdict]} verdict recorded${v.vIssues === "unlabelled" ? " (no blocking finding named)" : ""}, task not closed${sessionNote("verifier session", v.verifier)}${faultNote}`;
  if (v.verifier !== "none") {
    if (v.vv !== "none") return `Verifier session filed a ${VERDICT[v.vv].toLowerCase()} verdict${sessionNote("verifier session", v.verifier)}`;
    if (v.vManager === "BLOCKED") return "Verifier session stuck, the Manager filed BLOCKED";
    if (STUCK.includes(v.verifier)) return "Verifier session stuck";
    if (IDLE.includes(v.verifier)) return "Verifier session idle";
    if (v.verifier === "ghost" || v.verifier === "ghostStopped") return "Verifier session is a ghost row (no process)";
    if (v.verifier === "ghostGone") return v.vfiled ? "Verifier session is a ghost row gone quiet, verdict filed" : "Verifier session is a ghost row gone quiet, no verdict";
    if (v.verifier === "failed") return "Verifier session failed, no verdict";
    if (v.verifier === "finished") return v.vfiled ? "Verifier session gone, verdict filed" : "Verifier session gone, no verdict";
    return "Verifier session working";
  }
  if (v.lastTask === "none") {
    if (STUCK.includes(v.worker)) return "Task session stuck";
    if (IDLE.includes(v.worker)) return "Task session idle";
    if (v.worker === "ghost" || v.worker === "ghostStopped") return "Task session is a ghost row (no process)";
    if (v.worker === "ghostGone") return "Task session is a ghost row gone quiet, no report";
    if (v.worker === "failed") return "Task session failed, no report";
    if (v.worker === "finished") return "Task session gone, no report";
    return "Task session working";
  }
  if (v.lastTask === "DIED") return "Attempt marked DIED, no report";
  if (v.lastTask === "STOPPEDhead") return v.stopReason === "pause" ? "Task paused, WIP committed" : "Task stopped, WIP committed";
  if (v.lastTask === "BLOCKEDmgr") return "Task session stopped, the Manager filed BLOCKED";
  return `Task session reported ${v.lastTask}${sessionNote("task session", v.worker)}`;
};

const recordLabel = (from, to) => {
  if (to.merged && !from.merged) return from.pr === "clean" ? "the Manager's record merges the request" : "the Manager's record finds the task merged";
  if (to.vManager === "BLOCKED" && from.vManager !== "BLOCKED") return "the Manager's record stops the stuck verifier session and files BLOCKED";
  if (from.verifier !== to.verifier && to.verifier === "finished" && from.vv !== "none" && to.vManager === from.vManager)
    return "the Manager's record stops the waiting verifier session; the verdict stands";
  if (to.vv !== from.vv) return "the Manager's record files the report that the verifier session left";
  if (to.lastTask === "DIED" && from.lastTask !== "DIED") return "the Manager's record marks the attempt DIED";
  if (to.lastTask === "BLOCKEDmgr" && from.lastTask !== "BLOCKEDmgr") return "the Manager's record stops the stuck task session and files BLOCKED";
  if (to.lastTask === "STOPPEDhead" && from.lastTask !== "STOPPEDhead") return "the Manager's record commits the WIP";
  return "the Manager runs record";
};

// Both close commands. The condition tells apart the arrows that leave one state. A close that merges and a close
// with no commit beyond the base (recorded merged with no merge) both say "merged at once"; the glossary says so.
const closeLabel = (from, to, how) => {
  if (closed(from)) return `the Manager closes the task again [${to.merged ? "merged now" : requestWords(to.pr)}]`;
  if (!closed(to)) return `${how} [verdict ${LEVEL[to.verdict]}]`;
  return `${how} [verdict passes, ${to.merged ? "merged at once" : requestWords(to.pr)}]`;
};

const sessionStep = (from, to) => {
  if (from.worker !== to.worker) return `the task session is now ${to.worker}`;
  if (from.verifier !== to.verifier) return `the verifier session is now ${to.verifier}`;
  if (from.pr !== to.pr) return `the code host shows the request ${to.pr}`;
  return null;
};

const HOST_SAYS = {
  clean: "ready to merge",
  behind: "behind the target branch",
  blocked: "blocked by a check",
  dirty: "in conflict",
};

export const step = (action, from, to) => {
  switch (action) {
    case "Launch": return from.worker !== "none" && (from.worker !== "finished" || from.verifier === "idle" || from.verifier === "idleQuiet" || from.verifier === "idleBlocked")
      ? "the Manager starts an attempt and stops the idle session first" : "the Manager starts an attempt";
    case "LaunchStopsIdleThenRefuses": return (to.worker === "ghostStopped" || to.verifier === "ghostStopped")
      ? "the Manager tries to start an attempt: the idle session turns into a ghost row, and the start is refused"
      : "the Manager tries to start an attempt: the idle session stops, and the start is refused";
    case "VerifyPlain": return "the Manager starts a verifier session";
    case "VerifyAgain": return "the Manager starts a verifier session again";
    case "VerifierFilesUnchecked": return "the verifier session files a failing verdict that names no blocking finding";
    case "RoleBreaks": return "an outside change breaks or deletes the role file";
    case "ExcludeBreaks": return "an outside change makes info/exclude read-only";
    case "OperatorRepairs": return "the operator repairs the broken file";
    case "CloseAuto": return closeLabel(from, to, "the Manager closes the task");
    case "CloseManual": return closeLabel(from, to, "the Manager closes the task and names the verdict");
    case "Stop": return from.worker === "busy" ? "the operator pauses the task session"
      : from.worker === "ghost" ? "the Manager stops the ghost task session, as record says: the row ends"
      : "the Manager stops the idle task session, as record says";
    case "Abandon": return "the Manager abandons the task";
    case "Merged": return "the Manager records the merge";
    case "Record": return recordLabel(from, to);
    case "Done": return "the Manager has nothing more to do";
    case "WorkerEnds": return from.lastTask === "none" ? "the task session ends without a report" : "the task session ends after its report";
    case "WorkerExits": return "the stopped task session exits";
    case "WorkerFails": return "the task session fails";
    case "WorkerIdles": return "the task session goes idle for good";
    case "WorkerAsks": return "the task session ends its turn with a question";
    case "WorkerPrompted": return "the task session waits on a permission prompt";
    case "WorkerGhosts": return "the task session's process dies, leaving a ghost row";
    case "WorkerGhostReturns": return "the Claude CLI starts the task session again";
    case "WorkerGhostStays": return "the task session's ghost row stays quiet for 30 minutes and counts as ended";
    case "VerifierGhosts": return "the verifier session's process dies, leaving a ghost row";
    case "VerifierGhostReturns": return "the Claude CLI starts the verifier session again";
    case "VerifierGhostStays": return "the verifier session's ghost row stays quiet for 30 minutes and counts as ended";
    case "WorkerFilesPass": return "the task session reports PASS";
    case "WorkerFilesIssues": return "the task session reports ISSUES";
    case "WorkerFilesBlocked": return "the task session reports BLOCKED";
    case "WorkerDirties": case "VerifierLeavesReport": return null;
    case "VerifierEnds": return from.vfiled ? "the verifier session ends after its verdict" : "the verifier session ends without a verdict";
    case "VerifierFails": return "the verifier session fails";
    case "VerifierIdles": return "the verifier session goes idle";
    case "VerifierWakes": return "the verifier session wakes up";
    case "VerifierQuiet": return "the verifier session stays idle for 30 minutes";
    case "VerifierAsks": return "the verifier session ends its turn with a question";
    case "VerifierPrompted": return "the verifier session waits on a permission prompt";
    case "VerifierFiles": return `the verifier session files its verdict [${LEVEL[to.vv]}]`;
    case "HostDecides": return `the code host marks the request ${HOST_SAYS[to.pr]}`;
    case "TargetMoves": return "another task or a reviewer moves the target branch on";
    case "CheckFails": return "the code host reports a failing check";
    case "CheckPasses": return "the code host reports all checks passing";
    case "SomeoneMerges": return "a reviewer merges the request on the code host";
    case "SomeoneCloses": return "a reviewer closes the request on the code host";
    case "SomeoneReopens": return "a reviewer reopens the request on the code host";
    case "OperatorOrdersStop": return "the operator writes a STOP order";
    case "OperatorLiftsStop": return "the operator lifts the STOP order";
    case "OperatorMerges": return "the operator merges the branch by hand";
    default: return sessionStep(from, to) ?? action;
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

export const glossary = {
  "the Manager": "The Claude session that runs the team: it runs run.py's commands (launch, verify, close, abandon, record) and follows the next step that record prints.",
  "the operator": "The person who owns the run: writes the standing orders, pauses work, repairs files and, in local mode, merges by hand.",
  "the task session": "The Claude session that does one attempt of the task in its own worktree and files one report.",
  "the verifier session": "The Claude session that checks the task session's work and files one verdict.",
  "record": "run.py record, the Manager's check of every task: it reads the sessions and the result rows, writes what it finds, and prints the next step.",
  "the code host": "The service that holds the request, such as GitHub, when the team merges through requests.",
  "the Claude CLI": "The claude command that runs the sessions; it can start a session whose process died.",
  "a reviewer": "A person who acts on the request on the code host, the operator included.",
  "an outside change": "An edit to the repository's files by a person or a program outside the team.",
  "another task": "Another task of the same run, whose merge moves the target branch on.",
  "attempt": "One run of a task session on the task; after the last one allowed (3 in run.py; a model config can set fewer), the Manager abandons the task.",
  "report": "The task session's result row: PASS, ISSUES or BLOCKED.",
  "PASS": "The task session says the work is done and checked.",
  "ISSUES": "The task session says the work is done but has problems that need another attempt.",
  "BLOCKED": "The work cannot go on without a decision; the task session or the Manager files it.",
  "DIED": "The row that record files when a task session ended without a report.",
  "verdict": "The verifier session's finding: passes, check-only or fails. Only a passing verdict lets the task merge.",
  "check-only": "The verifier session could only check part of the work; the task does not merge on it.",
  "blocking finding": "A problem that the verifier session marks as one that must be fixed before the task can pass.",
  "WIP": "Work in progress: the task session's changes that are not committed yet when it pauses or stops.",
  "STOP order": "The operator's standing order that pauses new attempts and merges until the operator lifts it.",
  "ghost row": "A session that still shows as running but has no process; after 30 quiet minutes it counts as ended.",
  "idle session": "A task or verifier session that has filed its result and waits; the next attempt stops it.",
  "request": "The pull request or merge request for the task's branch on the code host.",
  "merged at once": "The close merges the branch, or records the task as merged because the branch has no commit to merge.",
  "role file": "The file that says how a task session of this kind works; starting a session needs it.",
  "info/exclude": "Git's local ignore file; run.py writes to it before it starts a session.",
};
