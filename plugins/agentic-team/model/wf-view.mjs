// Overview view of Workflow.tla (wf-overview.cfg: the shipped hotfix workflow, impl then test, with the W4 escalation of a
// spec stage before impl, replace and cancel). Each chart state is the stage the instance waits on and where that stage is.

export const title = "One hotfix workflow instance: its stages, approvals and the W4 escalation (Workflow.tla)";

export const glossary = {
  "the Manager": "The Claude session that runs the team with run.py's commands.",
  "record": "run.py record, the Manager's check of every task; it opens approvals, applies defaults and prints hints.",
  "the stage session": "The Claude session that does one attempt of a stage task (the whole attempt lifecycle, Lifecycle.tla).",
  "the clock": "Time passing: an open approval reaches its due time.",
  "impl stage": "The stage task that changes the code (role software-engineer, approval auto).",
  "test stage": "The stage task that checks the merged change on the real surface (approval auto).",
  "spec stage": "The design stage that an escalation puts before impl; its approval is the Manager's.",
  "approval": "A Taskgraph decision node; the stages after a stage wait for it.",
  "instance": "The parent task of the stages; it is done when every stage is merged and every approval answered.",
};

const NAMES = { "+spec": "Spec stage", impl: "Impl stage", test: "Test stage" };
const ORDER = ["+spec", "impl", "test"];

const where = (v, s) => {
  const runs = Object.values(v.run[s]).slice(0, v.parts[s]);
  if (runs.includes("abandoned")) return "abandoned, orphan hint shown";
  if (runs.includes("busy")) return "running";
  if (runs.includes("idle")) return "reported, sessions kept";
  if (runs.every((r) => r === "done")) {
    if (v.appr[s] === "pending") return "merged, approval not open yet";
    if (v.appr[s] === "open") return v.due[s] ? "merged, approval past due" : "merged, approval open";
    return "merged and approved";
  }
  return "waiting to start";
};

const finished = (v, s) => where(v, s) === "merged and approved";

export const state = (v) => {
  if (v.inst === "merged") return "Instance merged";
  if (v.inst === "cancelled") return "Instance cancelled";
  const added = v.st["+spec"] === "created" ? " (spec added)" : "";
  const open = ORDER.filter((s) => v.st[s] === "created" && !finished(v, s));
  if (open.length === 0) return "Every stage merged and approved" + added;
  return `${NAMES[open[0]]} ${where(v, open[0])}${open[0] === "+spec" ? "" : added}`;
};

export const group = (v) => (v.inst !== "open" ? "end" : v.st["+spec"] === "created" ? "escalated" : "planned");
export const colors = { end: "teal", escalated: "orange", planned: "blue" };

export const step = (action, from, to) => {
  switch (action) {
    case "Launch": return "the Manager launches the stage";
    case "Report": return "the stage session files its report";
    case "Finish":
      return Object.values(to.run).some((r, i) => Object.values(r).includes("abandoned") &&
                                         !Object.values(Object.values(from.run)[i]).includes("abandoned"))
        ? "the Manager abandons the stage at the cap" : "record records the stage merged";
    case "OpenApproval": return "record opens the stage approval";
    case "ManagerApprove":  // past the due time the chart draws record's default only: both lead to the same state
      return Object.values(from.due).some(Boolean) ? null : "the Manager approves the stage";
    case "DueArrives": return "the clock passes the due time";
    case "ApplyDefault": return "record applies the default approve";
    case "Escalate": return "the Manager escalates: a spec stage goes before impl";
    case "Replace": return "the Manager replaces the abandoned stage";
    case "Cancel": return "the Manager cancels the instance";
    case "Settle": return "record marks the instance merged";
    case "Done": return null;
    default: return action;
  }
};
