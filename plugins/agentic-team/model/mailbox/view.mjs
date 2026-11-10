// Reader's view of Mailbox.tla: one region for the worker of the current attempt, one for its question
// and answer, one for its steer, one for the task. Use with every config; overview-ask.cfg and
// overview-steer.cfg are small enough (< 500 states) for the whole chart.

export const title = "Ask, answer and steer between the Manager and a worker (ADR 2026-11-09; code 3330fc7)";

// A TLA+ sequence or function on 1..n arrives as an object with keys from 1 (or as an array).
const list = (x) => (x == null ? [] : Array.isArray(x) ? x : Object.values(x));
const at = (f, k) => (f == null ? undefined : Array.isArray(f) ? f[k - 1] : f[k]);

const curSession = (v) => at(v.cur, v.attempt);
const alive = (p) => p === "busy" || p === "idle";

const workerLabel = (v) => {
  const s = curSession(v);
  const p = v.proc[s];
  const w = v.wst[s];
  const sessions = Object.keys(v.proc).filter((k) => alive(v.proc[k]));
  if (sessions.length > 1) return "Two live sessions (a resume copy)";
  if (sessions.length === 1 && list(v.untracked).includes(sessions[0])) return "Only an unrecorded copy runs";
  if (p === "failed") return "Resumed session failed (account)";
  if (p === "none") {
    if (w === "wait") return v.conv[s] === "lost" ? "Waiting, process and conversation gone" : "Waiting, no process";
    if (w === "done") return "Reported, no process";
    return v.conv[s] === "lost" ? "Process and conversation gone" : "No process";
  }
  if (v.bell[s]) return "Doorbell waiting in the session";
  if (w === "wait") return "Waiting for an answer";
  if (w === "checked") return "Report checked, about to file";
  if (w === "done") return "Reported";
  return list(v.seen[s]).length ? "Read the inbox, about to ack" : "Working";
};

const MAIL = {
  pending: "not delivered yet",
  delivered: "resumed with the doorbell",
  copied: "resume started a copy",
  acked: "acked by the worker",
  carried: "carried to the next brief",
  superseded: "replaced by a newer answer",
};
const mailLabel = (m) =>
  m.st === "rung" ? (m.via === "hook" ? "pointer waits for the hook" : "doorbell posted to the socket") : MAIL[m.st];

const msgsOf = (v, kind) => list(v.msgs).filter((m) => m.kind === kind && m.att === v.attempt);

const answerLabel = (v) => {
  if (!msgsOf(v, "ask").length) return "No question";
  const ans = msgsOf(v, "answer");
  if (!ans.length) return "Question open";
  return "Answer " + mailLabel(ans[ans.length - 1]);
};

const steerLabel = (v) => {
  const st = msgsOf(v, "steer");
  if (!st.length) return "No steer";
  return "Steer " + mailLabel(st[st.length - 1]);
};

const END = { report: "report filed", DIED: "DIED filed", FAILED: "failed end filed", STOPPED: "stopped", ABANDONED: "abandoned" };
const taskLabel = (v) => {
  if (v.taskEnd === "closed") return "Closed";
  if (v.taskEnd === "abandoned") return "Abandoned";
  const e = at(v.ends, v.attempt);
  const n = `Attempt ${v.attempt}`;
  return e === "none" ? `${n} running` : `${n}: ${END[e]}`;
};

export const state = (v) => ({
  Worker: workerLabel(v),
  Question: answerLabel(v),
  Steer: steerLabel(v),
  Task: taskLabel(v),
});

const changedMsg = (from, to) => {
  const a = list(from.msgs);
  const b = list(to.msgs);
  for (let i = 0; i < b.length; i++) {
    if (JSON.stringify(a[i]) !== JSON.stringify(b[i])) return { before: a[i], after: b[i] };
  }
  return null;
};
// The operator's run.py moved when its pc changed, or when it alone was deciding (a refused post keeps the pc).
const opMoved = (from, to) =>
  from.dpc.op !== to.dpc.op || (from.dpc.mgr === to.dpc.mgr && from.dpc.op === "decide" && from.dpc.mgr !== "decide");
const who = (from, to) => (opMoved(from, to) ? "the operator's run.py" : "run.py");
const newBell = (from, to) => Object.keys(to.bell).some((s) => to.bell[s] && !from.bell[s]);
const strayAdded = (from, to) => list(to.stray).length > list(from.stray).length;

const decideLabel = (from, to) => {
  const r = who(from, to);
  const c = changedMsg(from, to);
  const d = opMoved(from, to) ? "op" : "mgr";
  if (c && c.after.st === "carried") return `${r} drops a message of an ended attempt (Carried)`;
  if (to.dpc[d] === "resume") return `${r} stops the worker for a resume`;
  if (c && c.after.via === "hook" && to.dpc[d] === "idle")
    return c.before && c.before.via === "hook" ? `${r} touches the hook flag again` : `${r} touches the hook flag`;
  if (c && c.after.st === "rung") {
    if (strayAdded(from, to)) return `${r} posts the doorbell to a socket of the wrong session`;
    return newBell(from, to) ? `${r} posts the doorbell to the socket` : `${r} posts the doorbell; the worker holds it`;
  }
  if (c && c.after.sockF && !(c.before && c.before.sockF) && c.after.st === "pending" && c.after.tries === c.before.tries
      && to.dpc[d] === "decide") return `${r}'s socket post is refused`;
  if (c && c.after.st === "pending") return `${r} stops the worker; the process does not exit (the row stays pending)`;
  const t = at(from.cur, from.attempt);
  if (list(from.rowGone).includes(t) && to.dpc[d] === "idle") return `${r} finds no session row (record tries again)`;
  if (from.proc[t] === "failed" && from.dpc[d] === "decide" && list(from.msgs).some((m) => m.st === "pending"))
    return `${r} does not resume a failed session`;
  return `${r} finds the message already handled`;
};

const resumeLabel = (from, to) => {
  const r = who(from, to);
  const d = opMoved(from, to) ? "op" : "mgr";
  if (list(to.untracked).length > list(from.untracked).length) return `${r}'s resume starts a copy it does not record (note: on stderr)`;
  if (to.dpc[d] === "settle") return `${r}'s resume starts a copy (note: line)`;
  if (to.overflow) return `${r}'s resume needs a second copy`;
  if (Object.keys(to.ends).some((k) => to.ends[k] === "DIED" && from.ends[k] !== "DIED")) return `${r}'s resume fails: no transcript, DIED`;
  if (Object.keys(to.proc).some((s) => to.proc[s] === "failed" && from.proc[s] !== "failed")) return `${r} resumes; the session fails at once`;
  return `${r} resumes the session with the doorbell`;
};

export const step = (action, from, to) => {
  switch (action) {
    case "WorkerAsks": return "the worker asks and ends its turn";
    case "WorkerReadsInbox": return "the worker runs inbox";
    case "WorkerAcks": return "the worker acks what it read";
    case "WorkerChecksReport": return "check-report passes";
    case "WorkerReports": return "the worker files its report";
    case "Die": return "the worker's process dies";
    case "SupervisorStops": return "the supervisor stops the idle session";
    case "AccountFails": return "the worker's account fails";
    case "PidReused": return "another process takes the old pid";
    case "ProcessIgnoresStop": return "the worker's process stops answering claude stop";
    case "RowGone": return "claude agents no longer lists the worker's session";
    case "Answer": return "the Manager answers";
    case "ManagerSteers": return "the Manager steers";
    case "OperatorSteers": return "the operator steers from a terminal";
    case "RecordRetries": return "record retries the delivery";
    case "RecordTimesOut": return "no ack within pending_minutes";
    case "RecordFilesDied": {
      const k = Object.keys(to.ends).find((a) => to.ends[a] !== from.ends[a]);
      return to.ends[k] === "report" ? "record files the report it salvaged"
        : to.ends[k] === "FAILED" ? "record files the failed end (the account failed)" : "record files DIED";
    }
    case "RecordFilesFailed": return "record files the failed row";
    case "DeliverDecide": return decideLabel(from, to);
    case "DeliverResume": return resumeLabel(from, to);
    case "DeliverSettle": return `${who(from, to)} stops the original and records the copy`;
    case "Launch": return "the Manager launches the next attempt";
    case "Relaunch": return "the operator launches the abandoned task again (--attempt)";
    case "Close": return "the Manager closes the task";
    case "Abandon": return "the Manager abandons the task";
    case "ManagerStops": return "the Manager stops the attempt";
    case "Finished": return null;
    default: return action;
  }
};

export const group = (v) => {
  if (v.taskEnd !== "no") return "End";
  if (v.dpc.mgr !== "idle" || v.dpc.op !== "idle") return "Delivering";
  if (at(v.ends, v.attempt) !== "none") return "Ended";
  const s = curSession(v);
  if (v.wst[s] === "wait") return "Waiting";
  return "Working";
};

export const colors = {
  Working: "orange",
  Waiting: "blue",
  Delivering: "purple",
  Ended: "yellow",
  End: "tan",
};
