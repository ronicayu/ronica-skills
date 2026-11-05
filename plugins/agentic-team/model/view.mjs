// Full view of Lifecycle.tla (agentic-team 0.12.0): every state the Manager can tell apart in `record` and `status`.
// State labels are in the operator's words; step labels say what happens.

export const title = "Task attempt lifecycle (agentic-team 0.12.0)";

const LEVEL = {
  "artifact-verified": "passes",
  "check-only": "check-only",
  "verify-failed": "fails",
};
const STUCK = ["idleBlocked", "prompt"];
const IDLE = ["idle", "idleQuiet"];

const sessionNote = (who, s) => {
  if (s === "idleBlocked") return `, ${who} asked a question`;
  if (s === "prompt") return `, ${who} on a prompt`;
  if (IDLE.includes(s)) return `, ${who} idle`;
  if (s === "failed") return `, ${who} failed`;
  return "";
};

export const state = (v) => {
  if (v.abandoned) return "Abandoned";
  if (v.status === "done") {
    if (v.merged) return "Merged";
    if (v.pr === "none") return "Closed, branch waits for the merge";
    if (v.pr === "closed") return "Closed, request closed unmerged";
    if (v.pr === "dirty") return "Closed, request conflicts";
    if (v.pr === "behind") return "Closed, request behind";
    return "Closed, request open";
  }
  if (v.status === "open") return "Not started";
  if (v.lastTask === "STOPPED") return v.stopReason === "pause" ? "Paused, WIP not committed yet" : "Stopped, WIP not committed yet";
  if (v.verdict !== "none") return `Verdict ${LEVEL[v.verdict]} recorded, not closed${sessionNote("verifier", v.verifier)}`;
  if (v.verifier !== "none") {
    if (v.vv !== "none") return `Verdict ${LEVEL[v.vv]} filed${sessionNote("verifier", v.verifier)}`;
    if (v.vManager === "BLOCKED") return "Verifier stuck, filed BLOCKED";
    if (STUCK.includes(v.verifier)) return "Verifier stuck";
    if (IDLE.includes(v.verifier)) return "Verifier idle";
    if (v.verifier === "failed") return "Verifier failed, no verdict";
    if (v.verifier === "finished") return v.vfiled ? "Verifier gone, verdict filed" : "Verifier gone, no verdict";
    return "Verifier working";
  }
  if (v.lastTask === "none") {
    if (STUCK.includes(v.worker)) return "Worker stuck";
    if (IDLE.includes(v.worker)) return "Worker idle";
    if (v.worker === "failed") return "Worker failed, no result";
    if (v.worker === "finished") return "Worker gone, no result";
    return "Worker working";
  }
  if (v.lastTask === "DIED") return "Died, no result";
  if (v.lastTask === "STOPPEDhead") return v.stopReason === "pause" ? "Paused, WIP committed" : "Stopped, WIP committed";
  if (v.lastTask === "BLOCKEDmgr") return "Worker stopped, filed BLOCKED";
  return `Reported ${v.lastTask}${sessionNote("worker", v.worker)}`;
};

const recordLabel = (from, to) => {
  if (to.merged && !from.merged) return from.pr === "clean" ? "record merges the request" : "record finds it merged";
  if (to.vManager === "BLOCKED" && from.vManager !== "BLOCKED") return "record stops the stuck verifier, files BLOCKED";
  if (from.verifier !== to.verifier && to.verifier === "finished" && from.vv !== "none" && to.vManager === from.vManager)
    return "record stops the waiting verifier, the verdict stands";
  if (to.vv !== from.vv) return "record salvages the verifier's report";
  if (to.lastTask === "DIED" && from.lastTask !== "DIED") return "record files DIED";
  if (to.lastTask === "BLOCKEDmgr" && from.lastTask !== "BLOCKEDmgr") return "record stops the stuck worker, files BLOCKED";
  if (to.lastTask === "STOPPEDhead" && from.lastTask !== "STOPPEDhead") return "record commits the WIP";
  return "you run record";
};

const sessionStep = (from, to) => {
  if (from.worker !== to.worker) return `the worker is now ${to.worker}`;
  if (from.verifier !== to.verifier) return `the verifier is now ${to.verifier}`;
  if (from.pr !== to.pr) return `the request is now ${to.pr}`;
  return null;
};

export const step = (action, from, to) => {
  switch (action) {
    case "Launch": return from.worker !== "none" && (from.worker !== "finished" || from.verifier === "idle" || from.verifier === "idleQuiet" || from.verifier === "idleBlocked")
      ? "you launch an attempt (it stops the idle session)" : "you launch an attempt";
    case "LaunchStopsIdleThenRefuses": return "launch stops the idle session, then refuses";
    case "VerifyPlain": return "you start a verifier";
    case "VerifyAgain": return "you start a verifier (--again)";
    case "CloseAuto": return "you close";
    case "CloseManual": return `you close with verdict ${LEVEL[to.verdict]}`;
    case "Stop": return from.worker === "busy" ? "the operator orders a pause" : "you stop the idle worker (record's hint)";
    case "Abandon": return "you abandon the task";
    case "Merged": return "you record the merge";
    case "Record": return recordLabel(from, to);
    case "Done": return "nothing more to do";
    case "WorkerEnds": return "the worker ends";
    case "WorkerExits": return "the stopped worker exits";
    case "WorkerFails": return "the worker fails";
    case "WorkerIdles": return "the worker goes idle for good";
    case "WorkerAsks": return "the worker ends its turn with a question";
    case "WorkerPrompted": return "the worker hits a permission prompt";
    case "WorkerFilesPass": return "the worker reports PASS";
    case "WorkerFilesIssues": return "the worker reports ISSUES";
    case "WorkerFilesBlocked": return "the worker reports BLOCKED";
    case "WorkerDirties": case "VerifierLeavesReport": return null;
    case "VerifierEnds": return "the verifier ends";
    case "VerifierFails": return "the verifier fails";
    case "VerifierIdles": return "the verifier goes idle";
    case "VerifierWakes": return "the verifier wakes up";
    case "VerifierQuiet": return "30 quiet minutes pass";
    case "VerifierAsks": return "the verifier ends its turn with a question";
    case "VerifierPrompted": return "the verifier hits a permission prompt";
    case "VerifierFiles": return `the verifier files ${LEVEL[to.vv]}`;
    case "HostDecides": return `the host says ${to.pr}`;
    case "TargetMoves": return "the target branch moves on";
    case "CheckFails": return "a check fails";
    case "CheckPasses": return "the checks pass";
    case "SomeoneMerges": return "someone merges the request";
    case "SomeoneCloses": return "someone closes the request";
    case "SomeoneReopens": return "someone reopens the request";
    case "OperatorOrdersStop": return "the operator writes a STOP order";
    case "OperatorLiftsStop": return "the operator lifts the STOP order";
    case "OperatorMerges": return "the operator merges the branch";
    default: return sessionStep(from, to) ?? action;
  }
};

export const group = (v) => {
  if (v.abandoned || (v.status === "done" && v.merged)) return "End";
  if (v.status === "done") return "Closing";
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
