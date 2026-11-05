// Overview of Lifecycle.tla for the README: the main flow in about a dozen states.
// Use it with overview.cfg (FULL_ENV = FALSE, OPERATOR_PAUSES = TRUE).

export const title = "Task attempt lifecycle (agentic-team 0.12.1)";

const LEVEL = {
  "artifact-verified": "passes",
  "check-only": "check-only",
  "verify-failed": "fails",
};

export const state = (v) => {
  if (v.abandoned) return "Abandoned";
  if (v.status === "done") return v.merged ? "Merged" : "Closed, waiting for the merge";
  if (v.status === "open") return "Not started";
  if (v.lastTask === "STOPPED" || v.lastTask === "STOPPEDhead") return "Paused";
  if (v.verdict !== "none") return "Verdict recorded, not closed";
  if (v.verifier !== "none") {
    if (v.vv !== "none") return "Verdict filed";
    if (v.verifier === "busy") return "Verifier working";
    return "Verifier gone, no verdict";
  }
  if (v.lastTask === "none") return v.worker === "finished" ? "Worker gone, no result" : "Worker working";
  if (v.lastTask === "DIED") return "Died, no result";
  if (v.lastTask === "PASS") return "Reported PASS";
  return "Reported ISSUES or BLOCKED";
};

const recordLabel = (from, to) => {
  if (to.merged && !from.merged) return "record finds the branch merged";
  if (to.lastTask === "DIED" && from.lastTask !== "DIED") return "record files DIED";
  if (to.lastTask === "STOPPEDhead" && from.lastTask !== "STOPPEDhead") return "record commits the WIP";
  return "you run record";
};

export const step = (action, from, to) => {
  switch (action) {
    case "Launch": return from.attempt === 0 ? "you launch the first attempt" : "you launch the next attempt";
    case "VerifyPlain": case "VerifyAgain": return "you start a verifier";
    case "CloseAuto": case "CloseManual": return to.status === "done" ? "you close" : "you close: the verdict does not pass";
    // The README chart draws the pause only from "Worker working", where it normally happens. A pause from a
    // verifying or verdict state also leads to "Paused"; hiding those arrows keeps the chart readable.
    case "Stop":
      if (state(from) !== "Worker working") return null;
      return from.worker === "busy" ? "the operator orders a pause" : "you stop the idle worker (record's hint)";
    case "LaunchStopsIdleThenRefuses": return "launch stops the idle session, then refuses";
    case "Abandon": return "you abandon the task";
    case "Record": return recordLabel(from, to);
    case "Done": return "nothing more to do";
    case "WorkerEnds": return "the worker ends";
    case "WorkerExits": return "the stopped worker exits";
    case "WorkerFilesPass": return "the worker reports PASS";
    case "WorkerFilesIssues": return "the worker reports ISSUES";
    case "WorkerFilesBlocked": return "the worker reports BLOCKED";
    case "VerifierEnds": return "the verifier ends";
    case "VerifierFiles": return `the verifier files ${LEVEL[to.vv]}`;
    case "OperatorOrdersStop": return "the operator writes a STOP order";
    case "OperatorLiftsStop": return "the operator lifts the STOP order";
    case "OperatorMerges": return "the operator merges by hand";
    case "HostDecides": return `the host says ${to.pr}`;
    case "TargetMoves": return "the target branch moves on";
    case "CheckFails": return "a check fails";
    case "CheckPasses": return "the checks pass";
    case "SomeoneMerges": return "someone merges the request";
    case "SomeoneCloses": return "someone closes the request";
    case "SomeoneReopens": return "someone reopens the request";
    default: return action;
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
