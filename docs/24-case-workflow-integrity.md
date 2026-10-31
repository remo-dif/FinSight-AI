# Investigation case workflow integrity and keyword routing

Date: 2026-10-31. Baseline: `85a3d3e` (latest `origin/master` at task setup).
Branch: `fix/case-workflow-integrity`. Started from a clean worktree after fetch;
no changes to master. ECC RED/GREEN checkpoints were preserved. Separate agents
handled case regressions, routing and frontend; the final review covered the combined diff.

## 1. Confirmed defects and reproduction

The actual domain in `backend/app/schemas/cases.py` has statuses `new`,
`needs_evidence`, `escalated`, `resolved`, and decisions `escalate`,
`request_verification`, `false_positive`. Decision creation already required a
nonblank reason and mapped those decisions to `escalated`, `needs_evidence`,
`resolved`, respectively. The migration checks known enum strings, but does not
enforce a decision/status relationship or a decision reason across columns.

Before this patch:

1. Record `false_positive`, then PATCH `{ "status": "new" }`: the case reopened
   while retaining its false-positive decision. Other decisions also accepted
   incompatible status changes, including generic resolution after escalation.
2. PATCH `{ "assignee": "me", "decision": "escalate", "reason": "Replacement" }`
   on an already-decided case: HTTP 409 followed assignment/audit mutation in the
   session. Production dependency rollback normally prevented a durable write,
   but a caller reusing/committing that session could persist the rejected assignment.
   This is a confirmed mutation-order defect, not a claim every HTTP 409 persisted data.
3. Two PostgreSQL sessions read the same undecided case, then record different
   decisions: both requests returned 200 and generated audit entries; the final
   row reflected a competing overwrite. A cached ORM identity could also hide a
   decision committed by another session.
4. A legacy `resolved` record with no decision could be reopened or
   receive a new decision through the ordinary update endpoint. Audit failures
   also left pending mutations when the route was called with a reused session.
5. The router matched `"top" in message.lower()`, so `laptop`, `stop`, `desktop`,
   `topping` and similar embedded occurrences selected merchant analytics.

Reproductions are executable in the new workflow, PostgreSQL and keyword test files.
Existing ownership joins, 404 responses, reason validation, note authorship and
append-only note API were retained; no cross-user bypass was reproduced or introduced.

## 2. Explicit transition policy and compatibility

Before a decision is recorded, ordinary status updates follow this table. Identity
transitions are successful no-ops with no new status audit or timestamp change.

| Current status | Allowed ordinary target statuses |
| --- | --- |
| `new` | `new`, `needs_evidence`, `escalated` |
| `needs_evidence` | `needs_evidence`, `escalated` |
| `escalated` | `escalated`, `needs_evidence` |
| `resolved` | `resolved` only |

Any undecided non-resolved case may record exactly one of the existing decisions,
with the existing required reason; the decision sets its mapped status atomically.
Afterward, that decision pins the status. Same-status requests, assignment/unassignment
and new notes remain available. Repeating even an identical decision retains the
existing HTTP 409 contract; no idempotency-key protocol was added.

**Intentional compatibility restriction:** generic resolution after an `escalate` or
`request_verification` decision previously returned 200. It now returns 409, as do
regressions from an in-progress state to `new`. The existing domain does not specify
how to close a confirmed-fraud escalation, supersede verification, reopen or replace
a decision. This branch chooses a conservative freeze rather than inventing those
business operations. A separately designed, auditable resolution/reopen/redecision
operation is required for those workflows; this policy must be reviewed before rollout.
The tests explicitly cover this restriction rather than treating it as unchanged behavior.

Legacy resolved cases lacking decisions cannot reopen or receive new decisions;
assignment and same-status no-ops remain possible. Already-inconsistent recorded
decisions/statuses or blank stored reasons return 409 on PATCH and require review;
they are not silently repaired. Existing reads and append-only notes remain available.
No production records were inspected or changed. Review legacy data before rollout.

URLs, identifiers, response/request fields and enum values are unchanged. Empty or
schema-invalid updates retain HTTP 422; forbidden transitions and concurrent write
conflicts use HTTP 409 with controlled messages; foreign and missing cases retain
the same HTTP 404 response. Authentication, refresh logic and rate limits are unchanged.

## 3. Implementation

- `backend/app/services/case_workflow.py`: centralized transition table, existing
  decision mapping and complete validation before any mutation.
- `backend/app/api/routes/cases.py`: calculate requested changes/events first;
  conditional SQL update and corresponding audit writes commit together. Roll back
  SQL/audit/commit errors, including direct callers using an existing session.
- `backend/app/repositories/cases.py`: refresh ORM identities on scoped reads;
  compare-and-set the observed status, decision, reason and assignee, with ownership
  rechecked in the SQL predicate. A lost race yields 409 before audit insertion.
- `frontend/src/components/dashboard/case-workflow.tsx`: ordinary controls reflect
  the policy. Disable invalid targets, lock status after a decision/resolution and
  hide new-decision controls on legacy resolved cases. Assignment/notes stay usable.
- `backend/tests/test_case_workflow_integrity.py`: transition, atomicity and legacy regressions.
- `backend/tests/test_case_workflow_postgres.py`: real concurrent writes, stale sessions and authenticated HTTP.
- `backend/tests/test_keyword_routing.py`: standalone/embedded keyword and precedence regressions.
- `frontend/tests/e2e/investigations/workflow-integrity.spec.ts`: browser control regressions.
- `docs/24-case-workflow-integrity.md`: policy, evidence, compatibility and migration proposal.

## 4. Database consistency and concurrency limits

The state update and audit are one database transaction; rejected validation leaves
neither dirty case state nor pending audit entries. PostgreSQL tests synchronize two
independent sessions after the initial read using a barrier, then check one 200 and
one 409, the persisted winner and exactly its audit events. A separate test verifies
a stale identity-map session cannot overwrite a committed decision. An authenticated
HTTP test uses real PostgreSQL, real signed JWT validation and fresh request sessions;
it checks 401/200/409/422/404 and persistence after rejection.

No client revision/If-Match field was introduced. An old browser request can still
succeed if valid against the current freshly read server state. Snapshot comparison
does not detect an ABA cycle returning all compared fields to their earlier values;
it is not a monotonic revision protocol. `updated_at` remains informational: SQLite's
server timestamp representation and its bound datetime precision are unsuitable as
an interchangeable revision token. No-op requests intentionally skip a write/CAS.

PostgreSQL concurrency was verified at default READ COMMITTED isolation. Custom
stronger isolation can raise serialization errors; rollback is safe, but mapping or
retrying those errors as 409 is deferred. No lock-retry subsystem was added. Direct
SQL or other writers can bypass application policy because no new cross-column
constraints/version column were authorized. Such writers must not be treated as
protected by this API change. No schema migration was created.

## 5. Keyword routing

Only the `top` rule changes: `re.search(r"\btop\b", message.lower())`.
Standalone `top`, uppercase variants and punctuation-delimited natural queries
retain merchant routing. Embedded letters, Unicode letters, digits and underscores
do not make a standalone keyword. Tests cover laptop/stop/desktop/atop/topping,
case, punctuation, whitespace, Unicode adjacency and existing keyword priority.
Other rules and specialist precedence remain unchanged; no LLM/dependency was added.
This does not turn the remaining keyword router into a semantic language parser.

## 6. Actual validation and RED/GREEN evidence

Required settings used synthetic secrets/placeholder provider credentials. PostgreSQL
and password-protected Redis ran in isolated local containers on loopback ports 3124
and 3126. PostgreSQL concurrency/HTTP fixtures created and dropped their own schemas;
the existing migration smoke ran only against this disposable test database. Other
unit/API fixtures still use SQLite where defined. Browser API fixtures are simulated,
so browser passes are separate from the real PostgreSQL HTTP integration.

| Stage | Checkpoint | Actual result |
| --- | --- | --- |
| Router RED | `81a5913` | 12 failed, 18 passed |
| Router GREEN, including existing orchestrator tests | `696a1d3` | 32 passed |
| Workflow RED | `80d6c9a` | SQLite: 18 failed, 16 passed; PostgreSQL: 3 failed |
| Terminal/audit supplementary RED | `ef77efb` | 4 failed, 34 deselected |
| Frontend controls RED | `de7aefb` | 5 Chromium failures |
| Backend focused GREEN | `894bed1` | 52 passed, 149 deprecation warnings |
| Frontend focused GREEN | `68681b8` | 6 Chromium passed, including existing critical flow |
| Supplementary PostgreSQL HTTP/legacy coverage | `6230eb5` | Final full backend: 497 passed |

Initial collection attempts without required settings were setup failures, not RED
defect evidence. A first implementation check also caught an SQLite timestamp-CAS
representation mismatch; it was corrected before the GREEN checkpoint. No failing
test was skipped to obtain GREEN.

Commands actually executed (from `backend`, Python executable `../.venv/Scripts/python.exe`):

```text
python -m pytest tests/test_keyword_routing.py tests/test_orchestrator.py -q -p no:cacheprovider --tb=short
python -m pytest tests/test_case_workflow_integrity.py -q -p no:cacheprovider --tb=line
python -m pytest tests/test_case_workflow_postgres.py -q -p no:cacheprovider --tb=line
python -m pytest tests/test_case_workflow_integrity.py tests/test_case_workflow_postgres.py tests/test_cases.py tests/test_auth_authorization_audit.py -q -p no:cacheprovider --tb=short
python -m coverage run --source=app,evaluation -m pytest -q -p no:cacheprovider --tb=short
python -m coverage report --precision=2 --fail-under=80
```

The full suite was first 494 passed, then **497 passed, zero skipped, 161 existing
SQLAlchemy deprecation warnings, 38.01 seconds** after adding real HTTP and legacy
consistency coverage. Final coverage **89.15%** (2820 statements, 306 missed).
Case routes, repository and new transition service each have 100% statement coverage;
this is not proof all possible domain workflows are complete.

Ruff check across `backend` and scoped format checks of all seven changed Python
files pass. Frontend `npm run build`, `npm run typecheck`, `npm run lint` pass.
Targeted Chromium tests executed the new workflow spec plus existing critical-flow
spec. The complete six-project matrix then ran from `frontend` with
`PLAYWRIGHT_WEB_SERVER_COMMAND='npm run start -- -p 3101'` and
`npx playwright test --reporter=list,json --global-timeout=240000`:
**138 passed, 72 existing/viewport-specific skips, zero unexpected/flaky results,
zero runner errors; 171.383 seconds, exit 0.** The new five desktop workflow tests
run on Chromium, Firefox and WebKit and follow the existing mobile skip convention.
Ignored local artifacts are `backend/coverage/case-workflow-e2e.json` and `.log`.
The runner's existing `next start` standalone warning remains; no test-server
architecture change was made. `git diff --check`, full backend Ruff and scoped
format checks pass; the combined code/test diff was reviewed before delivery.

Delivery observation: remote `master` advanced to `6230eb5` while this work was
underway (confirmed with `git ls-remote`), so it already contains the code/test
checkpoints. No command in this task pushed master; code was authored on the
dedicated branch. The complete task diff must be reviewed against initial baseline
`85a3d3e`, not the subsequently advanced remote master. No history was rewritten.
The final documentation and all checkpoints are delivered on the requested branch.
The CI push filter covers main/master and the older CI-runner branch, not
`fix/case-workflow-integrity`. A dedicated branch push therefore does not itself
establish a new CI result; no PR or workflow change is made to bypass that policy.

## 7. Deferred independent case-ID migration proposal — not implemented

`InvestigationCase.transaction_id` is both primary key and FK to `transactions.id`.
Thus a transaction can have only one case; repeat investigations cannot have separate
ownership/state/decisions/history. Deleting that transaction cascades to its case
and notes. Current API `CaseResponse.id`, frontend selection/cache keys and note
`case_id` all use the transaction UUID. Audit JSON embeds the same legacy identifier.

A separately authorized expand/backfill/contract migration should:

1. Add an independent immutable case UUID plus an indexed non-unique transaction FK.
   Backfill one UUID per existing case, preserving a permanent legacy mapping. Validate
   row counts, ownership, decision/reason consistency and note references before cutover.
2. Backfill notes to a new FK referencing the case UUID; stage constraints and dual
   read/write compatibility before switching the primary key. Preserve authors and
   timestamps. Treat audit records as historical evidence: retain their legacy IDs and
   supply an explicit mapping/event rather than silently rewriting audit history.
3. Use an explicit versioned endpoint/identifier contract. Both IDs are UUIDs, so
   guessing whether `/api/cases/{id}` means transaction or investigation is unsafe.
   Keep v1 transaction-based access deterministic for its original mapped case during
   deprecation; expose independent case ID and transaction ID separately in v2.
4. Update frontend types, route clients, deep links, table selection, React keys,
   query caches and note requests. Test multiple cases for one transaction without
   cross-case notes/decisions or financial double counting. Preserve ownership through
   the transaction join; adding a case ID must not relax tenant checks.
5. Keep multiple-investigation creation disabled through a reversible rollout window.
   Retain old columns/mapping and a verified backup until old clients and FKs migrate.
   Rollback can restore v1 routing during that one-case window. Once multiple cases
   exist, collapsing back to a transaction PK is not lossless: require roll-forward
   or a separately approved reconciliation/export/restore, never discard investigations.
   Drop old keys only in a later reviewed contract migration after that window.

This proposal adds no columns, dependencies or routes in this branch.

## 8. Remaining risks and release boundary

- Conservative decision pinning needs domain/operations acceptance; explicit audited
  resolution/reopen/redecision and historical decision events remain separate work.
- Legacy inconsistency requires review and authorized remediation, not automatic repair.
- Public revision tokens, ABA detection, stronger isolation retries and protection
  from direct database writers are not supplied by this application-level patch.
- Case identity is still transaction identity; the migration above is deferred.
- Prior AWS proxy verification, real legacy-volume permission rollout and account-wide
  login policy remain open/deferred from the security cycle.
- No production provider/infrastructure/browser integration is claimed. No PR, merge
  or deployment is authorized by this task; pushing the dedicated branch is authorized.
