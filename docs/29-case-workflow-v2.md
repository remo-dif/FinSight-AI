# Case Workflow V2: follow-up, closure and integrity

Date: 2026-10-31. Base: `6a51d09` (`origin/master`, including PR #9 and repository-wide Ruff formatting enforcement).

## Confirmed limitation and preserved behavior

The original workflow correctly serialized concurrent initial decisions, enforced ownership through the transaction owner, and committed state and audit together. Its invariant fixed each initial decision to a status forever. Consequently, `escalate` and `request_verification` had no operational closure path. Replacing the initial decision with `false_positive` was deliberately forbidden, and remains forbidden.

V2 adds separate outcome and closure records. It does not reinterpret or overwrite historical decisions, invent a reviewer role, change case identifiers, implement reopening, or change document Q&A / finance Copilot behavior.

## State machine

| Current state / decision | Operation | Required information | Result |
|---|---|---|---|
| Undecided `new`, `needs_evidence`, `escalated` | Existing permitted PATCH | Existing validation | Existing transition policy, unchanged |
| Undecided, not resolved | Initial `escalate` decision | Initial reason | `escalated` |
| Undecided, not resolved | Initial `request_verification` decision | Initial reason | `needs_evidence` |
| Undecided, not resolved | Initial `false_positive` decision | Initial reason | `resolved`, existing behavior |
| `escalated` + initial `escalate`, no outcome | `escalation_outcome` | Investigation outcome/reason, expected revision | Same status; append outcome |
| `needs_evidence` + initial `request_verification`, no outcome | `verification_outcome` | Verification results/outcome, expected revision | Same status; append outcome |
| Either follow-up state, matching outcome exists | Explicit close | Separate closure reason, expected revision | `resolved`; append closure |
| V2 closed case | Assignment, status, decision, note, outcome, or another closure | Any | HTTP 409; no mutation |

Only one outcome and one closure are permitted. Outcomes are narrative findings, not a new fraud verdict taxonomy. Verification results/new evidence can be recorded in the required outcome text and existing notes before closure. No attachment or external verification provider is introduced. The initial decision and its reason remain unchanged after closure.

Already resolved false positives and legacy resolved cases do not require another closure. Their existing assignment/note behavior is preserved for compatibility. The strict terminal write prohibition applies to V2 closures (resolved with initial escalate/request_verification). Pre-existing inconsistent decision/status combinations are rejected for review rather than silently repaired.

## API and frontend

- `GET /api/cases/{case_id}/follow-ups`: owner-scoped history, chronological by monotonic revision.
- `POST /api/cases/{case_id}/follow-ups`: `{action: escalation_outcome | verification_outcome, reason, expected_revision}`; HTTP 201.
- `POST /api/cases/{case_id}/close`: `{reason, expected_revision}`; HTTP 200 with the case.
- Existing case responses gain `revision`; details also gain `follow_ups`. Existing status values, decision values, IDs, request bodies and routes remain supported. There are no alias endpoints or arbitrary status assignment additions.
- Whitespace-only/missing reasons, invalid action types, missing/negative revisions fail with 422. Reasons are trimmed and limited to 4,000 characters. An unauthorized session receives the existing 401; another owner's or nonexistent case returns 404; state, duplicate and stale revision conflicts return 409.

The interface displays initial decision/reason unchanged, chronological follow-up records, relevant next action, required reason, validation/conflict errors and terminal closure information. Successful or failed follow-up actions refresh case/list queries. Reasons remain available after a failed submission. Follow-up form state resets on case changes; matching case detail/revision is required before submitting. Backend checks remain authoritative. Existing UI API mocks test presentation and do not prove real database integration.

## Authorization

All existing and new actions require the authenticated active user and ownership of the underlying transaction. ADMIN is not treated as a global reviewer, and no assignee or frontend flag grants cross-user access. The project has USER/ADMIN but no reliable case-reviewer or tenant membership model. Therefore, the owner may record a follow-up and close their own investigation; this is not four-eyes approval or delegated review by a different analyst. A real reviewer/tenant delegation design remains a separate business and authorization change.

## Persistence and migration

Migration `20261031_0006` adds non-null `investigation_cases.revision` (existing rows default to 0) and `case_follow_ups`. Each record has a fresh UUID, case ID, required actor ID, action, reason, previous/resulting status, revision and timestamp. Case IDs remain transaction UUIDs for compatibility; follow-up IDs are independent UUIDs.

The table enforces known actions, non-empty reasons, positive revision, unique (case, action) and unique (case, revision), plus case/actor foreign keys and a case index. Actor deletion is restricted while referenced. Existing migration files and stored decisions are not rewritten. Downgrade drops follow-up history and the revision column; it is destructive to V2 history and requires a backup/operator decision. A V2-closed case retains its resolved status and original escalate/verification decision after downgrade, which old application rules consider inconsistent. Downgrading after V2 use therefore requires a separate data reconciliation plan; it is not a safe automatic rollback. Upgrade must precede application startup. Stop old application writers during rollout: an old process does not participate in revision accounting or terminal closure rules.

## Atomicity and concurrency

Every real state mutation increments the persisted revision with a conditional SQL UPDATE. The condition includes case ID, owner subquery, observed revision, status, decision/reason and assignee. Outcome, closure, existing PATCH and notes all participate; notes must participate so that a concurrent closure cannot accept evidence it did not observe. A repeated no-op assignment does not create events or advance revision.

New actions require the revision observed by the client. A stale client receives 409 even if the current status string is unchanged. Existing PATCH clients retain their previous request contract and server-side snapshot comparison; they do not gain pre-request stale-view detection unless they use the new lifecycle actions.

The revision update, new follow-up/note and audit event use the same SQLAlchemy transaction and connection. Audit exceptions or commit failures propagate and roll back the whole operation. No process-local lock, external provider call, LLM or automatic retry is used. PostgreSQL re-evaluates the conditional UPDATE after a competing writer commits, allowing one winner and rejecting the other with 409. Unique constraints provide additional duplicate protection.

## Audit integrity and threat boundary

New business audit events are `case.follow_up_recorded` and `case.closed`. Metadata includes case/follow-up identifiers, acting user (existing audit user field), action, previous/resulting status and revision. Full narrative reason is stored only in the owner-scoped follow-up, not duplicated into audit metadata. Existing initial-decision audit records and immutable initial decision fields remain intact through the API.

Append-only here is an application contract: there is no follow-up/audit update or delete API. This is not a cryptographically tamper-evident or privileged-database-administrator-resistant audit log. The existing shared database trust boundary still permits a sufficiently privileged direct SQL writer to alter records. Existing case deletion cascades can delete follow-ups; no public case/transaction deletion endpoint is introduced. Retention, restricted runtime SQL grants, a separate audit sink and externally anchored signatures/hash chains require an explicit operational and data-retention policy. A plain digest stored beside mutable data would not protect against an attacker able to rewrite both.

## Error Correction Codes (ECC) assessment

ECC means error-correcting codes here, not the ECC development-skill plugin. Potential relevance is accidental physical bit corruption in memory/storage or transfer. It does not establish actor authorization, transaction consistency, original provenance or protection against intentional rewriting.

PostgreSQL 16 WAL uses CRC checks, crash recovery and full-page images for specific failure modes. Page checksums are optional, not assumed enabled: operators can inspect `SHOW data_checksums`. The local test cluster and production are not claimed to have equivalent hardware, checksum, replication or backup settings. Storage redundancy, checksum monitoring, tested restores and hardware ECC RAM address infrastructure failures at the appropriate layer. Backups help recovery but can also preserve already-corrupt data; restore/integrity verification is necessary.

Application ECC would add redundant bytes, encoding/decoding CPU cost, new serialization formats, data backfill/migration, monitoring and recovery procedures without an identified application-specific corruption channel. Malicious changes could simply recompute the code. No application ECC is implemented. The implemented controls address the confirmed threat: authenticated stale/concurrent/invalid operations, duplicate outcomes and incomplete audit writes. Cryptographic integrity with keys or external anchoring would be more appropriate for deliberate tampering, but is deferred until the required trust boundary, retention and key management are defined.

Sources: [PostgreSQL 16 reliability](https://www.postgresql.org/docs/16/wal-reliability.html), [PostgreSQL 16 data checksums](https://www.postgresql.org/docs/16/checksums.html).

## Validation and separate critical review

Initial new lifecycle test execution reproduced the missing feature as one collection error (`CaseFollowUp` did not exist); this was not a passing test run. The first implementation then passed 55 focused new/existing case tests. New lifecycle + PostgreSQL-focused tests passed 16/16. The first full backend execution passed 606/606. A separate critical pass added populated-database upgrade preservation and commit-time audit failure tests, centralized the terminal guard and removed broad integrity-error-to-conflict translation. The resulting full backend execution passed 608, failed 0, skipped 0 (267 SQLAlchemy deprecation warnings) in 37.85 seconds, including migration upgrade/downgrade/upgrade, PostgreSQL/pgvector, Redis, HTTP ownership and concurrency tests. The final rerun from `backend/` again passed 608, failed 0, skipped 0, with 267 warnings in 37.86 seconds. The eight new PostgreSQL-specific scenarios all passed as part of this suite.

Commands actually run (Windows virtual environment Python; synthetic local settings only):

```text
cd backend
python -m ruff check .
python -m ruff format --check .
python -m pytest -q
cd ../frontend
npm run lint
npm run typecheck
npm run build
PLAYWRIGHT_WEB_SERVER_COMMAND="npm run start -- -p 3101" npx playwright test tests/e2e/investigations --project=chromium --reporter=list --global-timeout=120000
```

Ruff 0.16.10: lint PASS, 104 files formatted. Initial import ordering/fixture lint issues and formatter findings in new code were corrected before the final checks. Frontend lint, typecheck and production build PASS. Chromium investigation tests: 9 passed, 0 failed/skipped, including initial workflow regressions, escalation, verification, closure, required reason controls and conflict refresh. The new browser cases use explicitly mocked API responses; backend/HTTP/PostgreSQL tests supply the real transactional evidence.

The full supported Playwright suite was executed as six separate project commands to bound Windows worker shutdown:

```text
npx playwright test --project=<chromium|firefox|webkit|mobile|iphone|tablet> --reporter=list --global-timeout=120000
```

| Project | Passed | Failed assertions | Skipped | Runner result |
| --- | ---: | ---: | ---: | --- |
| Chromium | 45 | 0 | 1 | exit 0 |
| Firefox | 45 | 0 | 1 | exit 0 |
| WebKit | 45 | 0 | 1 | exit 0 |
| Mobile | 12 | 0 | 34 | exit 0 |
| iPhone | 12 | 0 | 34 | exit 1: two non-test runner/teardown timeout errors after tests completed |
| Tablet | 12 | 0 | 34 | exit 0 |

This first matrix therefore completed 171 passing test executions and 105 expected skips, but was **not an entirely green command run** due to the iPhone shutdown timeout. The skipped tests are the existing desktop-only flows on mobile and the existing mobile-only navigation test on desktop; the three new investigation scenarios also target desktop, reflecting the current workspace layout. No skip or assertion in an existing test was changed.

After the final UI corrections (resetting follow-up state per case, checking matching detail and replacing a misleading closed-case sign-in prompt), lint/typecheck/build were rerun and passed. The full investigation directory then passed 27/27 across Chromium, Firefox and WebKit in 44.0 seconds:

```text
npx playwright test tests/e2e/investigations --project=chromium --project=firefox --project=webkit --reporter=list --global-timeout=180000
```

An isolated full iPhone retry with two workers passed 12, failed 0, skipped 34, exit 0 in 12.3 seconds:

```text
npx playwright test --project=iphone --workers=2 --reporter=list --global-timeout=90000
```

The retry completes project coverage but does not erase the first timeout or prove its root cause. Intermittent Windows WebKit/iPhone runner teardown remains a test-infrastructure risk. No Playwright configuration, screenshots, trace/video settings, retry policy or CI gate was changed to obtain the retry result.

### Separate critical review and AI artifact audit

A separate final pass of the complete diff checked owner lookup on every route; closure barriers on legacy PATCH and notes; initial decision immutability; matching action/status; required outcome before close; stale client revision; one-winner PostgreSQL races; generated IDs; audit rollback at call time and commit time; populated upgrade; stable history ordering; safe React text rendering; and UI cache invalidation. This was a separate review pass by the implementing agent, not an independent human or separately delegated reviewer.

Confirmed issues caught and corrected during this pass: an overly broad integrity-error handler would have misreported an internal audit constraint failure as a retryable 409; a generic read-only notes message incorrectly suggested signing in after closure; and follow-up input needed reset/matching detail protection when selecting a different case. Those paths were corrected and the relevant suites rerun.

No production placeholder, mocked provider behavior, silent exception swallowing, process-local correctness lock, unbounded retry, dependency addition or unrelated change was found. Browser mocks remain explicitly test-only; database races use independent PostgreSQL sessions with deterministic barriers. The implementation does not claim privileged-SQL tamper resistance, delegated reviewer authority, mobile investigation controls, or safe post-use downgrade. External independent review and actual GitHub CI remain additional review gates; no PR is opened by this work.

## Files and scope

- `backend/app/models/case.py`, `models/__init__.py`: follow-up entity and case revision registration.
- `backend/alembic/versions/20261031_0006_case_follow_ups.py`: additive schema migration.
- `backend/app/repositories/cases.py`: persisted revision comparison/increment.
- `backend/app/services/case_workflow.py`: reject legacy PATCH writes after V2 closure.
- `backend/app/schemas/cases.py`: additive case/history fields and explicit action/closure contracts.
- `backend/app/api/routes/cases.py`: owner-scoped history, permitted outcome and close operations, notes serialized with closure, atomic audit/rollback.
- `backend/tests/test_case_workflow_v2.py`, `test_case_workflow_v2_postgres.py`: lifecycle, HTTP/isolation, audit failure and real concurrent operation tests.
- `frontend/src/lib/api.ts`, `components/dashboard/case-workflow.tsx`: typed requests and lifecycle presentation.
- `frontend/tests/e2e/investigations/workflow-v2.spec.ts`: browser regression scenarios.
- This document: design, integrity limits, ECC assessment and actual validation.

The README case-capability row links to this document and reflects explicit closure.

No hashing changes, dependencies, provider behavior, financial semantics, authentication, rate-limit rules, existing migrations or CI gates are changed. No production readiness claim is made. AWS deployment settings, privileged database tampering/retention, true reviewer delegation, restore drills and production rollout validation remain release/operational considerations.
