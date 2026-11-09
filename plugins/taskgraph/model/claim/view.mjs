// Reader's view of the claim model: one region per Manager, one for the issue.
const phase = {
  idle: "Not claiming",
  toPost: "Saw no live claim",
  posted: "Claim posted",
  confirming: "Lowest claim, confirming",
  patching: "Won, adding label",
  verifying: "Checking after label",
  held: "Holds the task",
  refused: "Lost",
  error: "Label write failed",
};

export const title = "tg start on GitHub: two Managers claim one task";

export const state = (v) => ({
  "Manager 1": phase[v.pc.m1],
  "Manager 2": phase[v.pc.m2],
  Issue: (v.open ? "Open" : "Closed") + (v.label ? ", in progress" : ""),
});

const who = (from, to) => (from.pc.m1 !== to.pc.m1 ? "Manager 1" : "Manager 2");

export const step = (action, from, to) => {
  switch (action) {
    case "Begin": return `${who(from, to)} runs tg start and reads the claims`;
    case "Post": return `${who(from, to)} posts a claim comment`;
    case "Decide": return `${who(from, to)} reads the claims again`;
    case "Confirm": return `${who(from, to)} waits 1.1 s and reads again`;
    case "Patch": return `${who(from, to)} reopens the issue and adds the label`;
    case "PatchFails": return `${who(from, to)}'s label write fails`;
    case "Verify": return `${who(from, to)} reads after the label`;
    case "Done": return `${who(from, to)} runs tg done`;
    case "Reopen": return `${who(from, to)} runs tg reopen`;
    case "Retry": return null;
    case "Age": return "60 s pass";
    case "Finished": return null;
    default: return action;
  }
};
