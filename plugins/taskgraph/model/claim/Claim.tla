---------------------------- MODULE Claim ----------------------------
\* The claim protocol of `tg start N` on GitHub: docs/plans/2026-11-08-taskgraph-github-backend-spec.md
\* section 8.1. With every FIX_* FALSE it is the first draft (main d1dbd04); the revised section 8.1 is
\* FIX_CONFIRM_ACTIVE, FIX_KEEP_VOID, FIX_STALE_NEEDS_AGE, FIX_OWNER_REUSE_YOUNG and FIX_CLOSE_STAMP TRUE.
\* FIX_CLOSE_PERMANENT, FIX_HOLD_CONFIRM and FIX_VERIFY_AFTER_PATCH are alternatives the check showed
\* are not needed (NOTES.md). One issue, two Managers (claimants). A claim comment may also void one stale claim.
EXTENDS Naturals, FiniteSets

CONSTANTS Claimants, MaxTries,
          ALLOW_LAG,        \* a list read can miss other people's comments (G-a property 2 fails)
          LAG_PREFIX,       \* with ALLOW_LAG: a read that holds my comment holds every lower id (spec G-a property 2); only newer comments can be missing
          ALLOW_AGE,        \* 60 s can pass at any moment, also while a claimant is between steps
          ALLOW_PATCH_FAIL, \* the label PATCH of step 10 can fail
          ALLOW_PERSON,     \* a person removes the label or closes / reopens the issue in the GitHub UI
          FIX_CONFIRM_ACTIVE, \* confirm read checks "my claim is the active one", not only "no lower unvoided claim"
          FIX_VERIFY_AFTER_PATCH, \* after the label PATCH, read again; if my claim is not active, exit 1
          FIX_STALE_NEEDS_AGE, \* stale = older than 60 s AND (no label OR closed after the claim)
          FIX_CLOSE_PERMANENT, \* a close ends every claim posted before it, also after a later reopen (issue timeline)
          FIX_HOLD_CONFIRM, \* step 5 (held by me) also does the confirm read before it reports held
          FIX_OWNER_REUSE_YOUNG, \* step 5 reuses my own claim only while it is younger than 60 s; else I post a new claim
          ALLOW_STALL,      \* a claimant can pause 60 s or more in the middle of tg start
          FIX_KEEP_VOID,    \* a loser whose comment also voids a claim edits it to keep the void, instead of deleting it
          FIX_CLOSE_STAMP   \* a close makes stale only the claims posted before it (comment created_at < closed_at)

VARIABLES comments, aged, nextId, open, label, pc, vid, mine, tries, closedOver
\* closedOver: ids of the comments posted before a close (with FIX_CLOSE_PERMANENT also before a label removal)

vars == <<comments, aged, nextId, open, label, pc, vid, mine, tries, closedOver>>

None == 0

Unvoided(S) == {c \in S : c.claim /\ ~\E d \in S : d.voids = c.id}
HasActive(S) == Unvoided(S) # {}
Active(S) == CHOOSE c \in Unvoided(S) : \A d \in Unvoided(S) : c.id <= d.id
Stale(c) ==
  IF FIX_CLOSE_PERMANENT THEN c.id \in closedOver \/ (~label /\ c.id \in aged)
  ELSE IF FIX_STALE_NEEDS_AGE THEN c.id \in aged /\ (~label \/ (~open /\ c.id \in closedOver))
  ELSE (~open /\ (~FIX_CLOSE_STAMP \/ c.id \in closedOver)) \/ (~label /\ c.id \in aged)

Own(m) == {c \in comments : c.owner = m}
\* A list read. Without lag it holds every comment. With lag it can miss others' comments,
\* never my own (read-after-write held 20 of 20, G23).
MaxOwn(m) == IF Own(m) = {} THEN 0 ELSE CHOOSE i \in {c.id : c \in Own(m)} : \A c \in Own(m) : c.id <= i
Reads(m) ==
  IF ~ALLOW_LAG THEN {comments}
  ELSE IF LAG_PREFIX THEN {Own(m) \cup {c \in comments : c.id <= k} : k \in MaxOwn(m)..nextId}
  ELSE {Own(m) \cup S : S \in SUBSET comments}

Init ==
  /\ comments = {} /\ aged = {} /\ nextId = 1
  /\ open = TRUE /\ label = FALSE
  /\ pc = [m \in Claimants |-> "idle"]
  /\ vid = [m \in Claimants |-> None]
  /\ mine = [m \in Claimants |-> None]
  /\ tries = [m \in Claimants |-> 0]
  /\ closedOver = {}

\* Steps 1-6: refresh, fetch the issue, read the comments, find the active claim.
Begin(m) ==
  /\ pc[m] = "idle" /\ tries[m] < MaxTries
  /\ tries' = [tries EXCEPT ![m] = @ + 1]
  /\ \E R \in Reads(m) :
       IF HasActive(R) /\ ~Stale(Active(R)) /\ Active(R).owner = m
          /\ ~(FIX_CLOSE_PERMANENT /\ Active(R).id \in closedOver)
          /\ ~(FIX_OWNER_REUSE_YOUNG /\ Active(R).id \in aged) THEN
          \* step 5: held by me; add the label only when it is missing
          /\ mine' = [mine EXCEPT ![m] = Active(R).id]
          /\ pc' = [pc EXCEPT ![m] = IF FIX_HOLD_CONFIRM THEN "confirming" ELSE IF open /\ label THEN "held" ELSE "patching"]
          /\ UNCHANGED <<vid, closedOver>>
       ELSE IF HasActive(R) /\ ~Stale(Active(R)) /\ Active(R).owner # m THEN
          \* step 6: held by another
          /\ pc' = [pc EXCEPT ![m] = "refused"]
          /\ mine' = [mine EXCEPT ![m] = None]
          /\ UNCHANGED <<vid, closedOver>>
       ELSE
          \* step 7 comes next: post a claim, voiding the stale one if there is one
          /\ pc' = [pc EXCEPT ![m] = "toPost"]
          /\ vid' = [vid EXCEPT ![m] = IF HasActive(R) THEN Active(R).id ELSE None]
          /\ mine' = [mine EXCEPT ![m] = None]
  /\ UNCHANGED <<comments, aged, nextId, open, label, closedOver>>

\* Step 7: post one comment (void marker first, then the claim marker).
Post(m) ==
  /\ pc[m] = "toPost"
  /\ comments' = comments \cup {[id |-> nextId, owner |-> m, voids |-> vid[m], claim |-> TRUE]}
  /\ mine' = [mine EXCEPT ![m] = nextId]
  /\ nextId' = nextId + 1
  /\ pc' = [pc EXCEPT ![m] = "posted"]
  /\ UNCHANGED <<aged, open, label, vid, tries, closedOver>>

Mine(m) == CHOOSE c \in comments : c.id = mine[m]
\* My claim was posted before a close of the issue (the issue timeline shows it).
Ended(m) == FIX_CLOSE_PERMANENT /\ mine[m] \in closedOver
DropMine(m) ==
  comments' = {c \in comments : c.id # mine[m]}
              \cup {[c EXCEPT !.claim = FALSE] : c \in {d \in comments : d.id = mine[m] /\ d.voids # None /\ FIX_KEEP_VOID}}

\* Steps 8-9: read again; the winner is the lowest unvoided claim.
Decide(m) ==
  /\ pc[m] = "posted"
  /\ \E R \in Reads(m) :
       IF HasActive(R) /\ Active(R).id = mine[m] /\ ~Ended(m) THEN
          /\ pc' = [pc EXCEPT ![m] = "confirming"] /\ UNCHANGED comments
       ELSE
          /\ DropMine(m) /\ pc' = [pc EXCEPT ![m] = "refused"]
  /\ UNCHANGED <<aged, nextId, open, label, vid, mine, tries, closedOver>>

\* Step 10: wait 1.1 s, read again (the confirm read).
Lost(m, R) ==
  IF FIX_CONFIRM_ACTIVE THEN ~(HasActive(R) /\ Active(R).id = mine[m]) \/ Ended(m)
  ELSE \E c \in Unvoided(R) : c.id < mine[m]
Confirm(m) ==
  /\ pc[m] = "confirming"
  /\ \E R \in Reads(m) :
       IF Lost(m, R) THEN
          /\ DropMine(m) /\ pc' = [pc EXCEPT ![m] = "refused"]
       ELSE
          /\ pc' = [pc EXCEPT ![m] = "patching"] /\ UNCHANGED comments
  /\ UNCHANGED <<aged, nextId, open, label, vid, mine, tries, closedOver>>

\* Step 10 (and step 5): PATCH state open, labels += tg:in-progress.
Patch(m) ==
  /\ pc[m] = "patching"
  /\ open' = TRUE /\ label' = TRUE
  /\ pc' = [pc EXCEPT ![m] = IF FIX_VERIFY_AFTER_PATCH THEN "verifying" ELSE "held"]
  /\ UNCHANGED <<comments, aged, nextId, vid, mine, tries, closedOver>>

PatchFails(m) ==
  /\ ALLOW_PATCH_FAIL /\ pc[m] = "patching"
  /\ pc' = [pc EXCEPT ![m] = "error"]      \* exit 1; the claim comment stays
  /\ UNCHANGED <<comments, aged, nextId, open, label, vid, mine, tries, closedOver>>

Verify(m) ==
  /\ pc[m] = "verifying"
  /\ \E R \in Reads(m) :
       IF HasActive(R) /\ Active(R).id = mine[m] /\ ~Ended(m) THEN
          /\ pc' = [pc EXCEPT ![m] = "held"] /\ UNCHANGED comments
       ELSE
          /\ DropMine(m) /\ pc' = [pc EXCEPT ![m] = "refused"]
  /\ UNCHANGED <<aged, nextId, open, label, vid, mine, tries, closedOver>>

\* The holder's `tg done` and `tg reopen`. Neither posts a comment.
Done(m) ==
  /\ pc[m] = "held"
  /\ open' = FALSE /\ label' = FALSE
  /\ pc' = [pc EXCEPT ![m] = "idle"]
  /\ closedOver' = closedOver \cup {c.id : c \in comments}
  /\ UNCHANGED <<comments, aged, nextId, vid, mine, tries>>

EndClaims == closedOver' = IF FIX_CLOSE_PERMANENT THEN closedOver \cup {c.id : c \in comments} ELSE closedOver
Reopen(m) ==
  /\ pc[m] = "held"
  /\ label' = FALSE
  /\ pc' = [pc EXCEPT ![m] = "idle"]
  /\ EndClaims
  /\ UNCHANGED <<comments, aged, nextId, open, vid, mine, tries>>

\* A refused or failed run ends; the Manager can run `tg start` again later.
Retry(m) ==
  /\ pc[m] \in {"refused", "error"}
  /\ pc' = [pc EXCEPT ![m] = "idle"]
  /\ UNCHANGED <<comments, aged, nextId, open, label, vid, mine, tries, closedOver>>

\* 60 s pass for one claim comment.
Midway == {"toPost", "posted", "confirming", "patching", "verifying"}
Age ==
  /\ ALLOW_AGE
  /\ (ALLOW_STALL \/ \A m \in Claimants : pc[m] \notin Midway)
  /\ \E c \in comments : c.id \notin aged /\ aged' = aged \cup {c.id}
  /\ UNCHANGED <<comments, nextId, open, label, pc, vid, mine, tries, closedOver>>

PersonRemovesLabel ==
  /\ ALLOW_PERSON /\ label /\ label' = FALSE
  /\ EndClaims
  /\ UNCHANGED <<comments, aged, nextId, open, pc, vid, mine, tries>>

PersonCloses ==
  /\ ALLOW_PERSON /\ open /\ open' = FALSE /\ label' = FALSE
  /\ closedOver' = closedOver \cup {c.id : c \in comments}
  /\ UNCHANGED <<comments, aged, nextId, pc, vid, mine, tries>>

Finished ==
  /\ \A m \in Claimants : pc[m] \in {"idle", "held"} /\ (pc[m] = "idle" => tries[m] = MaxTries)
  /\ UNCHANGED vars

Next ==
  \/ \E m \in Claimants :
       Begin(m) \/ Post(m) \/ Decide(m) \/ Confirm(m) \/ Patch(m) \/ PatchFails(m) \/ Verify(m)
       \/ Done(m) \/ Reopen(m) \/ Retry(m)
  \/ Age \/ PersonRemovesLabel \/ PersonCloses
  \/ Finished

Spec == Init /\ [][Next]_vars

\* ---- Rules, in the reader's words ----

\* At most one Manager believes it holds the task (gets exit 0 and starts work).
OneHolder == Cardinality({m \in Claimants : pc[m] = "held"}) <= 1

\* A Manager that believes it holds the task is the one GitHub shows as the holder:
\* its claim is the active claim.
HolderIsActive ==
  \A m \in Claimants : pc[m] = "held" => (HasActive(comments) /\ Active(comments).owner = m)

\* When two Managers both hold the task, GitHub shows a claim conflict (two unvoided claims),
\* so the failure is visible, not silent (spec G-c).
DoubleHoldIsVisible ==
  Cardinality({m \in Claimants : pc[m] = "held"}) >= 2 => Cardinality(Unvoided(comments)) >= 2

\* A Manager that lost leaves no claim comment of this attempt behind.
LoserLeavesNoClaim ==
  \A m \in Claimants : (pc[m] = "refused" /\ mine[m] # None) => ~\E c \in comments : c.id = mine[m] /\ c.claim

=============================================================================
