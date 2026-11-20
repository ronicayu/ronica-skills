---- MODULE Workflow ----
\* One workflow instance of scripts/run.py (agentic-team workflow templates, W2 and W3, with the W4 commands as planned in
\* docs/design/workflow-templates.md sections 8, 9 and 11): the stage tasks that `add --workflow` creates, their
\* dependencies, their approval decisions, the parts of a split stage, and the instance's end. A new module, not a
\* refinement of Lifecycle.tla: each attempt of a stage task is one abstract run (launch, report, done or abandoned).
\* Lifecycle.tla checks what happens inside an attempt: following record's hints it ends merged or abandoned with no
\* dead end. This module assumes exactly that (NOTES.md, "Workflow.tla", the interface assumption).
\*
\* Stage ids are strings. A split stage has parts 1..parts[s]; part 1 is the stage task itself (stage_split). The
\* escalation slot "+spec" is the one stage that `stage escalate spec --before impl` (W4) can create.
\*
\* W4 = FALSE is the code of W2 and W3 as it is: no escalate, downgrade, replace or cancel; an abandoned stage ends the
\* run, and the run must then show the `stage-orphaned` hint (orphan_note). W4 = TRUE adds the planned commands.
\* Each REGRESS_* constant, when TRUE, restores a bug or drops a guard, so its regress-wf-*.cfg must break.

EXTENDS Naturals, FiniteSets

CONSTANTS WF,            \* "check", "feature" or "hotfix": which workflow (the stage graphs below)
          MaxParts,      \* the parts a split stage may have (stage_split)
          MaxAdj,        \* [workflow_policy] max_adjustments: escalations plus downgrades per instance (2)
          MaxRepl,       \* [workflow_policy] max_replacements: replacements per stage (1)
          MaxRechoose,   \* bound on `stage rechoose` (an owner override, outside MaxAdj); not a code limit
          OnTimeout,     \* on_timeout of the rule that raises a stage to `human`: "approve" or "hold"
          W4,            \* TRUE: escalate, downgrade, replace and cancel exist (planned, phase W4)
          OPERATOR_FAIR, \* TRUE: the owner answers an open human approval in the end
          LATE_RULES,    \* TRUE: a split part's SCOPE may match a rule that the instance SCOPE did not (recheck_rules)
          REGRESS_SINK_ORPHAN,  \* an abandoned stage that nothing depends on gets no stage-orphaned hint (before the W3 fix)
          REGRESS_RECHOOSE_RULES, \* rechoose drops the rules that recheck_rules added to the record (before the W3 fix)
          REGRESS_SPLIT_APPROVAL,      \* the approval of a split stage opens when part 1 merges (before the W2 review fix)
          REGRESS_SKIP_RULE,           \* downgrade may skip a stage that a rule requires
          REGRESS_ESCALATE_LOOP,       \* no adjustment bound: escalate and downgrade any number of times, the escalated stage too
          REGRESS_NO_CONTRACT,         \* add --workflow keeps the edges of a skipped optional stage (no contraction)
          REGRESS_DOWNGRADE_DONE_ONLY, \* downgrade only marks the stage done-skipped; its dependents keep the edge to it
          REGRESS_INSERT_RUNNING,      \* escalate inserts before a stage with a busy or merged part
          REGRESS_NO_DEFAULT           \* an open approval has no default at its due time

ASSUME WF \in {"check", "feature", "hotfix"}
ASSUME OnTimeout \in {"approve", "hold"}
ASSUME MaxParts \in 1..3 /\ MaxAdj \in Nat /\ MaxRepl \in Nat /\ MaxRechoose \in Nat

VARIABLES
  st,        \* st[s]: "absent" (never created, or removed by rechoose), "created" (a stage task), "skipped" (downgrade)
  deps,      \* deps[s]: the stages whose tasks and approval decisions the task of s depends on (tg dep)
  parts,     \* parts[s]: the parts of the stage (1 unless split)
  run,       \* run[s][k]: "none", "busy" (an attempt runs), "idle" (its report is filed, its sessions are kept),
             \*            "done" (verified and merged), "abandoned"
  appr,      \* appr[s]: "none" (auto, or skipped), "pending" (the decision exists, not open), "open", "approved", "defaulted"
  due,       \* due[s]: the due time of the open approval has passed
  adj,       \* adjustments made: escalations plus downgrades
  escCount,  \* escalations per stage type
  repl,      \* repl[s]: replacements of stage s
  inst,      \* the instance: "open", "merged" (every stage merged and approved), "cancelled"
  ruleEver,  \* the stages that a matched rule requires, as the workflow record holds them (add, and recheck_rules)
  rechosen   \* rechoose runs so far

vars == <<st, deps, parts, run, appr, due, adj, escCount, repl, inst, ruleEver, rechosen>>

\* ---------------------------------------------------------------- the workflows

\* check: a project workflow that has every feature the model needs in five stages: an optional stage between two
\* others (ux), an optional stage that a rule forces on and raises to `human` (spec), a split stage (impl), and an auto
\* sink (test). spec comes after ux only, so a contraction matters (prd -> ux? -> spec).
\* feature and hotfix: the shipped files (templates/workflows/feature.md, hotfix.md).
AfterOf ==
  CASE WF = "check"   -> [prd |-> {}, ux |-> {"prd"}, spec |-> {"ux"}, impl |-> {"spec"}, test |-> {"impl"}]
    [] WF = "feature" -> [prd |-> {}, ux |-> {"prd"}, spec |-> {"prd", "ux"}, impl |-> {"spec"}, test |-> {"impl"}]
    [] WF = "hotfix"  -> [impl |-> {}, test |-> {"impl"}]
Base == DOMAIN AfterOf
Optional == CASE WF = "check" -> {"ux", "spec"} [] WF = "feature" -> {"ux"} [] WF = "hotfix" -> {}
SplitStages == IF WF = "hotfix" THEN {} ELSE {"impl"}
\* A rule (billing, say) matches the instance SCOPE at add: require_stage = "spec", approval = {spec = "human"}.
RuleRequired == IF WF = "check" THEN {"spec"} ELSE {}
\* A rule that only a split part's SCOPE matches (recheck_rules after stage_split): require_stage = "ux".
LateRule == IF LATE_RULES /\ WF = "check" THEN {"ux"} ELSE {}

EscSlot == "+spec"
EscTypes == {"spec"}
EscTargets == {"impl"}
Slots == Base \cup {EscSlot}
TypeOf(s) == IF s = EscSlot THEN "spec" ELSE s

\* stage_approval: the highest of the stage's value, a matching rule's `approval`, and the floor of its verify kind.
\* stages.toml: prd, ux, spec manager; impl, test auto. The rule raises check's spec to human, and check's project sets
\* the workflow value `approval: manager` on its split impl stage, so that a split stage has an approval. An escalated
\* stage gets the library level (manager).
LevelOf == [s \in Slots |->
  IF s = "spec" /\ WF = "check" THEN "human"
  ELSE IF s = "impl" /\ WF = "check" THEN "manager"
  ELSE IF s \in {"prd", "ux", "spec", EscSlot} THEN "manager"
  ELSE "auto"]

\* ---------------------------------------------------------------- derived

Parts(s) == 1..parts[s]
StageDone(s) == st[s] = "created" /\ \A k \in Parts(s) : run[s][k] = "done"
ApprOK(s) == appr[s] \in {"none", "approved", "defaulted"}
\* What Taskgraph and launch read: a dependency is satisfied when it is done (a downgraded stage is `tg done`) and its
\* approval decision is done. waiting_for and refuse_unmerged_deps in launch.
Satisfied(u) == st[u] = "skipped" \/ (StageDone(u) /\ ApprOK(u))
Started(s) == \E k \in Parts(s) : run[s][k] # "none"

\* The upstream closure over the current edges, skipped stages included.
RECURSIVE Reach(_, _)
Reach(S, n) == IF n = 0 THEN S ELSE Reach(S \cup UNION {deps[u] : u \in S}, n - 1)
Above(s) == Reach(deps[s], Cardinality(Slots))

\* workflows.contracted: an `after` stage that is not kept is replaced by its own upstream stages.
RECURSIVE Contract(_, _)
Contract(S, kept) == UNION {IF a \in kept THEN {a} ELSE Contract(AfterOf[a], kept) : a \in S}

\* What add --workflow (and rechoose) creates for a choice W of optional stages: build_plan, then create_stage.
Layout(W) ==
  LET kept == (Base \ Optional) \cup W IN
  [st    |-> [s \in Slots |-> IF s \in kept THEN "created" ELSE "absent"],
   deps  |-> [s \in Slots |-> IF s \in kept
                               THEN (IF REGRESS_NO_CONTRACT THEN AfterOf[s] ELSE Contract(AfterOf[s], kept))
                               ELSE {}],
   parts |-> [s \in Slots |-> 1],
   run   |-> [s \in Slots |-> [k \in 1..MaxParts |-> "none"]],
   appr  |-> [s \in Slots |-> IF s \in kept /\ LevelOf[s] # "auto" THEN "pending" ELSE "none"],
   due   |-> [s \in Slots |-> FALSE]]

\* plan_with_rules / apply_rules: a rule's optional stage is forced on; --skip of it is refused.
Choices(rules) == {W \in SUBSET Optional : (rules \cap Optional) \subseteq W}

\* orphan_note: an abandoned stage task gets `stage-orphaned` when a task in its `blocks` is not done: a dependent stage,
\* or its own approval decision (which depends on it). A sink stage with an auto approval has nothing in `blocks`.
Waiters(s) == {d \in Slots : st[d] = "created" /\ s \in deps[d] /\ ~StageDone(d)}
OrphanHint(s) == ~REGRESS_SINK_ORPHAN \/ appr[s] \in {"pending", "open"} \/ Waiters(s) # {}
Orphaned == {s \in Slots : st[s] = "created" /\ \E k \in Parts(s) : run[s][k] = "abandoned"}
OrphanHinted == \E s \in Orphaned : OrphanHint(s)

\* A human approval that a rule holds (on_timeout = "hold"): open_approval sets no due time; it waits for the owner.
Held(s) == st[s] = "created" /\ LevelOf[s] = "human" /\ OnTimeout = "hold" /\ appr[s] = "open"
HeldOnOperator == \E s \in Slots : Held(s)
Settled == inst # "open"

\* ---------------------------------------------------------------- the attempt, abstract (Lifecycle.tla)

\* cmd_launch: refuses while a dependency or a decision it depends on is not done (waiting_for).
Launch(s, k) ==
  /\ inst = "open" /\ st[s] = "created" /\ k \in Parts(s) /\ run[s][k] = "none"
  /\ \A u \in deps[s] : Satisfied(u)
  /\ run' = [run EXCEPT ![s][k] = "busy"]
  /\ UNCHANGED <<st, deps, parts, appr, due, adj, escCount, repl, inst, ruleEver, rechosen>>

\* The worker files its report; its sessions may be kept for a revision (the turn is over).
Report(s, k) ==
  /\ st[s] = "created" /\ run[s][k] = "busy"
  /\ run' = [run EXCEPT ![s][k] = "idle"]
  /\ UNCHANGED <<st, deps, parts, appr, due, adj, escCount, repl, inst, ruleEver, rechosen>>

\* The attempt lifecycle ends: verified and merged (record's merge, mark_merged), or abandoned at the cap.
Finish(s, k) ==
  /\ st[s] = "created"
  /\ \/ run[s][k] = "idle" /\ run' = [run EXCEPT ![s][k] = "done"]
     \/ run[s][k] \in {"busy", "idle"} /\ run' = [run EXCEPT ![s][k] = "abandoned"]
  /\ UNCHANGED <<st, deps, parts, appr, due, adj, escCount, repl, inst, ruleEver, rechosen>>

\* ---------------------------------------------------------------- approvals

\* open_approval (record and close, at the merge; approve_due for a pending one): the decision opens once every part of
\* the stage is merged (stage_parts_of). REGRESS_SPLIT_APPROVAL: once the stage task (part 1) is merged.
OpenApproval(s) ==
  /\ st[s] = "created" /\ appr[s] = "pending"
  /\ IF REGRESS_SPLIT_APPROVAL THEN run[s][1] = "done" ELSE StageDone(s)
  /\ appr' = [appr EXCEPT ![s] = "open"] /\ due' = [due EXCEPT ![s] = FALSE]
  /\ UNCHANGED <<st, deps, parts, run, adj, escCount, repl, inst, ruleEver, rechosen>>

\* stage_approve --by manager: refused while a part is not merged; accepted pending or open.
ManagerApprove(s) ==
  /\ st[s] = "created" /\ LevelOf[s] = "manager" /\ appr[s] \in {"pending", "open"} /\ StageDone(s)
  /\ appr' = [appr EXCEPT ![s] = "approved"]
  /\ UNCHANGED <<st, deps, parts, run, due, adj, escCount, repl, inst, ruleEver, rechosen>>

\* stage_approve --by operator, once the owner has answered.
OperatorAnswers(s) ==
  /\ st[s] = "created" /\ LevelOf[s] = "human" /\ appr[s] = "open" /\ StageDone(s)
  /\ appr' = [appr EXCEPT ![s] = "approved"]
  /\ UNCHANGED <<st, deps, parts, run, due, adj, escCount, repl, inst, ruleEver, rechosen>>

\* The clock passes due_at (manager_due_hours, human_due_hours). A held approval has no due time.
DueArrives(s) ==
  /\ appr[s] = "open" /\ ~due[s] /\ ~Held(s)
  /\ due' = [due EXCEPT ![s] = TRUE]
  /\ UNCHANGED <<st, deps, parts, run, appr, adj, escCount, repl, inst, ruleEver, rechosen>>

\* approve_due (record), or stage_approve --default: the default `approve` at the due time.
ApplyDefault(s) ==
  /\ appr[s] = "open" /\ due[s] /\ ~REGRESS_NO_DEFAULT
  /\ appr' = [appr EXCEPT ![s] = "defaulted"]
  /\ UNCHANGED <<st, deps, parts, run, due, adj, escCount, repl, inst, ruleEver, rechosen>>

\* ---------------------------------------------------------------- W2/W3 commands

\* stage_split: only while the stage task (part 1, `parts[0]` in the code) has no attempt; later parts are not checked.
\* The new part has the same upstream; every follower of part 1 (the approval decision, the later stages) depends on it.
\* recheck_rules then reads the part's SCOPE: a rule that matches it is added to the record (LATE_RULES).
Split(s) ==
  /\ inst = "open" /\ s \in SplitStages /\ st[s] = "created" /\ parts[s] < MaxParts /\ run[s][1] = "none"
  /\ parts' = [parts EXCEPT ![s] = @ + 1]
  /\ \E R \in SUBSET {r \in LateRule : st[r] = "created"} : ruleEver' = ruleEver \cup R
  /\ UNCHANGED <<st, deps, run, appr, due, adj, escCount, repl, inst, rechosen>>

\* stage_rechoose: the owner's override, only while no stage has started; every child is removed and the plan is made
\* again (here: the same workflow with another choice of optional stages). The rules are matched again by
\* matching_rules on the record's SCOPE and the area, so a rule that only recheck_rules found is dropped (record.update
\* rules=applied) when REGRESS_RECHOOSE_RULES. An escalated stage goes with the rest (an override is outside the limits).
Rechoose ==
  /\ inst = "open" /\ rechosen < MaxRechoose
  /\ \A s \in Slots : ~Started(s)
  /\ \E W \in Choices(IF REGRESS_RECHOOSE_RULES THEN RuleRequired ELSE ruleEver) :
       LET L == Layout(W) IN
       /\ st' = L.st /\ deps' = L.deps /\ parts' = L.parts /\ run' = L.run /\ appr' = L.appr /\ due' = L.due
  /\ rechosen' = rechosen + 1
  /\ UNCHANGED <<adj, escCount, repl, inst, ruleEver>>

\* ---------------------------------------------------------------- W4 commands (planned)

\* stage escalate spec --before b: a new stage with b's upstream, b then depends on it and its approval. Limits: MaxAdj,
\* once per type, b not done and no part busy (a kept idle session is stopped: the part goes back to waiting, and its
\* next launch is `--cause escalated`, exempt from the cap: Lifecycle.tla, ESCALATIONS).
Escalate(b) ==
  LET e == EscSlot
      t == TypeOf(EscSlot) IN
  /\ W4 /\ inst = "open"
  /\ b \in EscTargets /\ st[b] = "created"
  /\ (adj < MaxAdj /\ escCount[t] = 0) \/ REGRESS_ESCALATE_LOOP
  /\ st[e] = "absent" \/ (REGRESS_ESCALATE_LOOP /\ st[e] = "skipped")
  /\ IF REGRESS_INSERT_RUNNING THEN \A k \in Parts(b) : run[b][k] # "abandoned"
     ELSE \A k \in Parts(b) : run[b][k] \in {"none", "idle"}
  /\ st' = [st EXCEPT ![e] = "created"]
  /\ deps' = [deps EXCEPT ![e] = deps[b], ![b] = deps[b] \cup {e}]
  /\ parts' = [parts EXCEPT ![e] = 1]
  /\ run' = [run EXCEPT ![e] = [k \in 1..MaxParts |-> "none"],
                        ![b] = [k \in 1..MaxParts |-> IF run[b][k] = "idle" THEN "none" ELSE run[b][k]]]
  /\ appr' = [appr EXCEPT ![e] = IF LevelOf[e] # "auto" THEN "pending" ELSE "none"]
  /\ due' = [due EXCEPT ![e] = FALSE]
  /\ adj' = adj + 1 /\ escCount' = [escCount EXCEPT ![t] = @ + 1]
  /\ UNCHANGED <<repl, inst, ruleEver, rechosen>>

\* stage downgrade s: skips an optional stage with no attempt (`tg done`, stage_state=skipped, its approval closed with
\* it). Its dependents take its upstream edges (the contraction of add); REGRESS_DOWNGRADE_DONE_ONLY keeps the edge
\* to the done-skipped task, as section 8 words it ("dependents unblock naturally"). Never a rule's stage or an
\* escalated one; counts toward MaxAdj.
Downgrade(s) ==
  /\ W4 /\ inst = "open" /\ st[s] = "created"
  /\ s \in Optional \/ (REGRESS_ESCALATE_LOOP /\ s = EscSlot)
  /\ \A k \in Parts(s) : run[s][k] = "none"
  /\ adj < MaxAdj \/ REGRESS_ESCALATE_LOOP
  /\ s \notin ruleEver \/ REGRESS_SKIP_RULE
  /\ st' = [st EXCEPT ![s] = "skipped"]
  /\ appr' = [appr EXCEPT ![s] = "none"]
  /\ deps' = IF REGRESS_DOWNGRADE_DONE_ONLY THEN deps
             ELSE [d \in Slots |-> IF s \in deps[d] THEN (deps[d] \ {s}) \cup deps[s] ELSE deps[d]]
  /\ adj' = adj + 1
  /\ UNCHANGED <<parts, run, due, escCount, repl, inst, ruleEver, rechosen>>

\* stage replace s: a new task of the same type, the dependents moved to it, the old one detached; one part here.
\* Only where record printed stage-orphaned (the Manager follows hints), at most MaxRepl per stage.
Replace(s) ==
  /\ W4 /\ inst = "open" /\ s \in Orphaned /\ OrphanHint(s) /\ repl[s] < MaxRepl
  /\ \E k \in Parts(s) : run[s][k] = "abandoned" /\ run' = [run EXCEPT ![s][k] = "none"]
  /\ repl' = [repl EXCEPT ![s] = @ + 1]
  /\ UNCHANGED <<st, deps, parts, appr, due, adj, escCount, inst, ruleEver, rechosen>>

\* stage cancel: skips every not-started stage and abandons the instance; also only on the stage-orphaned hint. A stage
\* that runs in a parallel branch is abandoned with it (its sessions stopped, as cmd_abandon does), so that no session
\* outlives the instance (NoSessionAfterEnd).
Cancel ==
  /\ W4 /\ inst = "open" /\ OrphanHinted
  /\ inst' = "cancelled"
  /\ run' = [s \in Slots |-> [k \in 1..MaxParts |-> IF run[s][k] \in {"busy", "idle"} THEN "abandoned" ELSE run[s][k]]]
  /\ UNCHANGED <<st, deps, parts, appr, due, adj, escCount, repl, ruleEver, rechosen>>

\* ---------------------------------------------------------------- the end

\* The instance's derived status is done: every stage task merged, every approval answered.
Settle ==
  /\ inst = "open"
  /\ \A s \in Slots : st[s] = "created" => StageDone(s) /\ ApprOK(s)
  /\ inst' = "merged"
  /\ UNCHANGED <<st, deps, parts, run, appr, due, adj, escCount, repl, ruleEver, rechosen>>

\* The end states: settled; or, without W4, an abandoned stage whose stage-orphaned hint tells the Manager to report it.
Done ==
  /\ Settled \/ (~W4 /\ OrphanHinted)
  /\ UNCHANGED vars

\* ---------------------------------------------------------------- spec

Init ==
  /\ \E W \in Choices(RuleRequired) :
       LET L == Layout(W) IN
       /\ st = L.st /\ deps = L.deps /\ parts = L.parts /\ run = L.run /\ appr = L.appr /\ due = L.due
  /\ adj = 0 /\ escCount = [t \in EscTypes |-> 0] /\ repl = [s \in Slots |-> 0]
  /\ inst = "open" /\ ruleEver = RuleRequired /\ rechosen = 0

\* The steps that happen in the end when they stay possible: the Manager follows record's hints, the sessions finish,
\* the clock moves. Each of them moves forward and is bounded, so weak fairness of the whole set is enough.
FairNext ==
  \/ \E s \in Slots, k \in 1..MaxParts : Launch(s, k) \/ Report(s, k) \/ Finish(s, k)
  \/ \E s \in Slots : OpenApproval(s) \/ ManagerApprove(s) \/ DueArrives(s) \/ ApplyDefault(s) \/ Replace(s)
  \/ Settle \/ Cancel

\* The Manager's choices (split, escalate, downgrade) and the owner's (rechoose, a human answer) are not fair.
Next ==
  \/ FairNext
  \/ \E s \in Slots : OperatorAnswers(s) \/ Split(s) \/ Downgrade(s)
  \/ \E b \in Slots : Escalate(b)
  \/ Rechoose
  \/ Done

Spec == Init /\ [][Next]_vars /\ WF_vars(FairNext) /\ WF_vars(OPERATOR_FAIR /\ \E s \in Slots : OperatorAnswers(s))

\* Only REGRESS_ESCALATE_LOOP passes MaxAdj; states one step past it are checked, not explored.
AdjConstraint == adj <= MaxAdj + 1

\* ---------------------------------------------------------------- rules

RunStates == {"none", "busy", "idle", "done", "abandoned"}
TypeOK ==
  /\ st \in [Slots -> {"absent", "created", "skipped"}]
  /\ deps \in [Slots -> SUBSET Slots]
  /\ parts \in [Slots -> 1..MaxParts]
  /\ run \in [Slots -> [1..MaxParts -> RunStates]]
  /\ appr \in [Slots -> {"none", "pending", "open", "approved", "defaulted"}]
  /\ due \in [Slots -> BOOLEAN]
  /\ adj \in 0..(MaxAdj + 2) /\ escCount \in [EscTypes -> 0..(MaxAdj + 2)] /\ repl \in [Slots -> 0..MaxRepl]
  /\ inst \in {"open", "merged", "cancelled"} /\ ruleEver \subseteq Slots /\ rechosen \in 0..MaxRechoose

Acyclic == \A s \in Slots : s \notin Above(s)

\* No stage waits on a stage that does not exist: every dependency of a stage that is not done is a task (a created
\* stage, or a downgraded one, which is `tg done`). Liveness covers "can never finish".
NoGhostDeps ==
  \A s \in Slots : (st[s] = "created" /\ ~StageDone(s)) => \A u \in deps[s] : st[u] \in {"created", "skipped"}

\* Approvals cannot be bypassed: a part that has started has every created stage above it (through skipped stages too)
\* merged and approved, or approved by default.
NoBypass ==
  \A s \in Slots : st[s] = "created" =>
    \A k \in Parts(s) : run[s][k] \in {"busy", "idle", "done"} =>
      \A u \in Above(s) : st[u] = "created" => StageDone(u) /\ ApprOK(u)

\* The W2 review's bug: the approval of a split stage never opens while a part is unmerged.
SplitApprovalAfterAllParts ==
  \A s \in Slots : appr[s] \in {"open", "approved", "defaulted"} => StageDone(s)

\* A stage that a rule requires (at add, or later by recheck_rules) is never removed while the instance is open.
RuleStagesKept == inst = "open" => \A s \in ruleEver : st[s] = "created"

\* An escalated stage is never downgraded (rechoose, the owner's override, may remove it).
EscalatedKept == st[EscSlot] # "skipped"

\* The adjustment bound, once per type, and the replacement bound: with them escalation terminates.
AdjBound ==
  /\ adj <= MaxAdj
  /\ \A t \in EscTypes : escCount[t] <= 1
  /\ \A s \in Slots : repl[s] <= MaxRepl

\* No stage session runs once the instance has ended.
NoSessionAfterEnd == Settled => \A s \in Slots : \A k \in Parts(s) : run[s][k] \notin {"busy", "idle"}

\* An escalation (or a downgrade's contraction) never changes the edges of a stage with a busy part.
NoInsertIntoBusy ==
  [][\A s \in Slots : deps'[s] # deps[s] => \A k \in Parts(s) : run[s][k] # "busy"]_vars

\* Liveness: every instance ends merged or cancelled, or is blocked only on an approval the owner holds, or (without
\* W4) on an abandoned stage with its stage-orphaned hint.
Liveness == <>[](Settled \/ HeldOnOperator \/ (~W4 /\ OrphanHinted))

====
