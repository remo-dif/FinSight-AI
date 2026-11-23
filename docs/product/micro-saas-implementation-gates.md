# Micro-SaaS Pilot Implementation Gates and Effort Estimate

## Purpose and estimate basis

This document estimates the work required to move FinSight-AI from its current
individual-user portfolio foundation to a controlled B2B pilot for one-organization
professional teams of 2-5 users. It is a planning artifact, not authorization to implement.

### Evidence labels

- **Repository fact:** Verified from current repository documentation or code structure.
- **Estimate:** A reasoned range subject to discovery and architecture review.
- **Commercial hypothesis:** A belief about customers or willingness to pay that has not
  been validated by repository evidence.

### Global assumptions

- One experienced full-stack engineer familiar with the repository performs most work.
- Product, security, legal/privacy, and infrastructure decision owners are available for
  bounded review; their elapsed waiting time is excluded from person-days.
- Existing FastAPI, SQLAlchemy/Alembic, PostgreSQL, Next.js, authentication, audit, case,
  upload, RAG, chat, and CI foundations are reused.
- The pilot supports one organization per user, 2-5 seats, two roles, manual provisioning,
  and essential invitations only.
- AUTH-01 and AUDIT-01 remain protected and require separate approval if implementation
  must change them.
- No automated billing, custom roles, organization switching, advanced lifecycle, or
  routine operator content access is included.
- Estimates include design, implementation, tests, review fixes, and documentation, but
  exclude customer/legal procurement, cloud lead time, external penetration testing, and
  the 4-6 week live pilot itself.
- Existing automated tests reduce regression risk but do not establish production
  readiness, tenant isolation, regulatory suitability, or operational reliability.

## Summary estimate

| Gate | Estimated effort |
| --- | ---: |
| Gate 0 — Product and security policy decisions | 3-6 person-days |
| Gate 1 — Organization schema, migration and tenancy foundation | 8-14 person-days |
| Gate 2 — Membership, RBAC and invitations | 8-13 person-days |
| Gate 3 — Tenant isolation across existing application features | 15-25 person-days |
| Gate 4 — Pilot operations | 15-26 person-days |
| Gate 5 — Security verification, deployment and readiness | 10-18 person-days |
| **Total** | **59-102 person-days** |

The total is implementation effort, not elapsed calendar time. For one developer, review,
policy, partner, infrastructure, and remediation latency make a realistic calendar span
longer than the raw 12-20 working-week conversion. Parallel reviewers can reduce elapsed
time but not the core engineering effort.

## Gate 0 — Product and security policy decisions

### Scope and deliverables

- Decide and record exact retention/deletion, residency, revocation, export, usage-limit,
  and support/incident policies.
- Interview qualified design partners and measure current workflow, volume, handling time,
  data types, roles, and willingness to pay.
- Confirm that shared team workflow is necessary before building tenancy.
- Produce approved ADRs/policy records, a data inventory, threat-model delta, and a pilot
  data-processing boundary.
- Define which demonstrations may use synthetic versus contractually permitted data.

### Existing code and artifacts that can be reused

- `PRODUCT-BRIEF.md` and the organization capability contract.
- Current security documentation, ownership tests, deployment design, and data models.
- Existing RAG evaluation/cost work and rate-limit design as inputs to usage policy.

### Dependencies

- Product owner, security owner, legal/privacy input, infrastructure owner, and at least
  two reachable design partners.
- Workload and data-residency requirements from prospective partners.

### Major risks

- Policies are selected without customer evidence.
- Legal or residency constraints make the intended architecture uneconomic.
- Team tenancy is built even though partners would accept a concierge single-user pilot.

### Estimate and assumptions

**3-6 person-days** of engineering/product analysis and documentation. This excludes
calendar time waiting for interviews, legal advice, contracts, or decision approval.

### Acceptance criteria

- All six mandatory policies have named owners, approved values/procedures, and dates.
- Data inventory covers database, object storage, embeddings, caches, jobs, logs, exports,
  backups, and providers.
- At least two qualified prospects confirm their current workflow and whether shared access
  is required; this is evidence, not necessarily a signed pilot.
- Pilot scope and non-goals are approved without ambiguous “later in the pilot” additions.

### Tests required

- No application tests are required for documentation alone.
- Review policy decisions against tabletop scenarios: member removal, deletion request,
  export request, provider outage, suspected tenant leak, and support request.

### Go/no-go

- **GO:** Policies are approved and partner evidence supports a shared team workflow.
- **NO-GO:** No credible design partner, no willingness-to-pay signal, unresolved residency
  or support constraints, or a single-user concierge workflow can test the same thesis.

## Gate 1 — Organization schema, migration and tenancy foundation

### Scope and deliverables

- Architecture decision for single-organization membership and server-derived context.
- Minimal organization and membership schema plus migration journal/checks.
- One private migration organization and admin membership per existing user.
- Additive `organization_id` propagation strategy for tenant-owned roots and children.
- Tenant-context dependency and repository contract without changing the authentication
  model unless separately approved.
- Dual user-and-organization scope during migration; no shared access yet.

### Existing code that can be reused

- SQLAlchemy models, Alembic migrations, async session patterns, UUID identifiers, current
  user ownership predicates, and migration test infrastructure.
- Active-user authentication dependency and current authorization regression tests.

### Dependencies

- Gate 0 approved.
- Complete ownership/data inventory and explicit migration/cutover plan.
- Separate approval if AUTH-01 or AUDIT-01 must change.

### Major risks

- Orphan or indirectly owned rows receive the wrong tenant.
- Adding organization scope weakens current user isolation during partial rollout.
- Audit, embeddings, object keys, or derived data cannot be reconciled reliably.
- Rollback becomes unsafe after writes use mixed ownership models.

### Estimate and assumptions

**8-14 person-days.** Assumes the current schema has consistent user ownership and data
volume is small enough for bounded migration batches. Discovery of ambiguous ownership or
large live datasets increases the range.

### Acceptance criteria

- Migration preflight identifies all tenant-owned data and rejects ambiguity.
- Each existing user maps to exactly one separate organization; no data is merged.
- Backfill is restartable, count-reconciled, and reversible before cutover.
- Existing APIs retain user isolation and behavior while organization scope is additive.
- Database constraints prevent invalid membership and cross-tenant parentage where modeled.

### Tests required

- Alembic upgrade/downgrade and migration smoke tests on disposable PostgreSQL.
- Backfill idempotency, interruption/resume, orphan detection, and reconciliation tests.
- Existing authorization suite plus negative two-user/two-organization foundation tests.
- Concurrency tests for migration and new writes during the compatibility phase.

### Go/no-go

- **GO:** Ownership is unambiguous, rollback is demonstrated, and existing isolation tests
  remain green.
- **NO-GO:** Any tenant-owned data cannot be assigned deterministically or dual-scope
  operation permits access wider than current user ownership.

## Gate 2 — Membership, RBAC and invitations

### Scope and deliverables

- Enforce one active organization per user and the 2-5 seat policy.
- Implement only `organization_admin` and `reviewer` permissions.
- Manual organization/first-admin provisioning through a controlled runbook or narrow
  command.
- Essential hashed, single-use, expiring invitation create/accept/revoke flow.
- Minimal member/invitation UI and clear failure/revocation states.
- Last-admin, duplicate-invite, email-binding, and concurrent-acceptance safeguards.

### Existing code that can be reused

- Existing user model, email validation, password/authentication flows, token hashing
  patterns, rate limiting, API error handling, and frontend authenticated-session state.
- Existing role dependency patterns as implementation references, not as tenant policy.

### Dependencies

- Gate 1 tenant foundation.
- Approved seat limit and revocation propagation policy.
- Approved email ownership/invitation acceptance policy.
- AUTH-01/AUDIT-01 approval if protected implementations require modification.

### Major risks

- Invitation theft, replay, enumeration, or accepting an invite for the wrong identity.
- Stale sessions retain access after removal.
- Existing global `ADMIN` semantics leak into organization authorization.
- Concurrent changes remove the last admin or create duplicate membership.

### Estimate and assumptions

**8-13 person-days.** Assumes existing email/password identity remains and email delivery
may be concierge/manual for the pilot. Adding a production email provider, verification,
password reset, or templating broadens scope.

### Acceptance criteria

- Exactly one active membership per user and no organization selector/switcher.
- Permission matrix is explicit and enforced server-side.
- Invite tokens are hashed at rest, bound, single-use, expiring, non-enumerating, and
  idempotent under retries.
- Removal meets the approved revocation bound across API and frontend state.
- Last-admin and seat-limit invariants hold transactionally.

### Tests required

- RBAC table tests for both roles and anonymous/non-member access.
- Invite lifecycle, replay, expiry, wrong-email, duplicate, enumeration, and rate-limit
  tests.
- Concurrent acceptance, removal, role-change, and last-admin tests on PostgreSQL.
- Browser tests for acceptance, removed-member handling, and stale-cache clearing.

### Go/no-go

- **GO:** Invitation and revocation security properties are demonstrated without weakening
  current authentication.
- **NO-GO:** Authorization depends on client-selected context, stale unbounded JWT claims,
  or a protected AUTH-01 change without approval.

## Gate 3 — Tenant isolation across existing application features

### Scope and deliverables

- Convert repository/service access for transactions, cases, notes, decisions,
  assignments, uploads, storage, embeddings/RAG, document Q&A, chat, risk analysis, audit
  attribution, caches, and preliminary export paths to organization scope.
- Preserve current case integrity and user isolation during cutover.
- Tenant-aware storage keys, retrieval filters, cache keys, AI tool context, citations, and
  logs.
- Shared organization queue and evidence access for authorized team members.
- Remove transitional user predicates only after full-scope verification in a separate
  reviewed change.

### Existing code that can be reused

- Existing ownership-aware route/service queries and IDOR regression tests.
- Case revision/state machine, document ownership/citation validation, RAG filters,
  deterministic risk evaluation, structured AI tool boundaries, and frontend cache layer.

### Dependencies

- Gates 1 and 2.
- Approved organization ownership map and role/action matrix.
- A migration dataset that represents every domain relationship.

### Major risks

- Cross-tenant leakage through an indirect child, join, vector search, citation, cache,
  object path, job, or export.
- Over-correction keeps owner-only filters and prevents legitimate team collaboration.
- Existing case assignment is mistaken for an authorization mechanism.
- Audit changes accidentally modify protected AUDIT-01 behavior.

### Estimate and assumptions

**15-25 person-days.** This is the largest code-surface gate. The estimate assumes current
ownership checks are consistently centralized enough to adapt. Scattered raw queries,
hidden storage consumers, or audit schema changes increase effort.

### Acceptance criteria

- Authorized members share intended organization resources and only those resources.
- Adversarial IDs from another tenant never disclose existence or data.
- RAG chunks, citations, AI tool results, chat state, risk inputs, storage, and caches are
  tenant-consistent.
- Current case decision/transition guarantees and financial correctness remain intact.
- A reviewed inventory accounts for every tenant-owned and derived data path.

### Tests required

- Two-organization matrix for every list/detail/create/update/delete/action endpoint.
- Indirect-child, guessed-ID, pagination, filter, sort, bulk, and race tests.
- Cross-tenant RAG/vector retrieval, document citation, chat/tool, cache, storage, and risk
  tests.
- Existing backend, financial, auth, audit, and frontend regression suites.
- Browser tests using two organizations and multiple members within one organization.

### Go/no-go

- **GO:** Complete isolation matrix passes and legitimate intra-organization collaboration
  works without compatibility fallbacks.
- **NO-GO:** Any unscoped path remains, ownership inventory is incomplete, or isolation
  relies only on API conventions rather than repository/database boundaries.

## Gate 4 — Pilot operations: jobs, limits, retention, export and observability

### Scope and deliverables

- Implement approved fixed limits for seats, storage, upload, and AI usage/cost.
- Implement the approved retention/deletion and export contracts.
- Provide sufficient processing reliability: bounded synchronous processing with safe
  manual retry if proven adequate, or a minimal durable job workflow where required by
  workload and deletion/export guarantees.
- Add tenant-aware metrics, structured correlation, alerting, and sanitized support data.
- Produce provisioning, backup/restore, deletion, export, quota-exception, provider-outage,
  and incident runbooks.
- No generalized operator console or automated billing.

### Existing code that can be reused

- Upload validation/extraction, S3/local storage abstraction, RAG cost journal/evaluation,
  Redis rate limiting, structured AI operation events, readiness endpoints, and historical
  deployment/observability documentation.
- Current case/audit data as export sources after the contract is approved.

### Dependencies

- Gates 0-3 and exact approved policy values.
- Selected hosting/provider region and storage/backup design.
- Representative pilot workload and cost measurements.

### Major risks

- Request-bound uploads fail or duplicate under realistic latency.
- Deletion misses derived data, backups, provider artifacts, or failed jobs.
- Exports become high-value leakage artifacts.
- Usage counters race, undercount provider spend, or deny valid investigations.
- Observability captures sensitive content.

### Estimate and assumptions

**15-26 person-days.** The low end uses concierge provisioning, one fixed plan, minimal
customer-triggered export, and bounded processing with manual recovery where policy
permits. A durable general worker, scheduled retention engine, rich dashboards, or multiple
plans moves beyond the range and should be deferred.

### Acceptance criteria

- Limits are atomic, tenant-scoped, observable, and produce clear non-leaking errors.
- Approved retention/deletion SLA is testable end-to-end across all data stores.
- Export is complete, organization-scoped, authenticated, expiring, audited, and cleaned up.
- Processing retries are idempotent and no ambiguous job can cross tenant scope.
- Operators can diagnose availability and usage without routine content access.
- Required runbooks have owners and have been exercised in tabletop or staging drills.

### Tests required

- Quota boundary, concurrency, reservation/reconciliation, and denial-of-wallet tests.
- Job idempotency, retry, crash recovery, duplicate delivery, and tenant-binding tests if a
  job mechanism is introduced.
- Retention/deletion inventory and SLA tests including objects, embeddings, caches, exports,
  and failed work.
- Export completeness, authorization, expiry, integrity, and cleanup tests.
- Log/trace redaction tests and observability failure-path checks.

### Go/no-go

- **GO:** Policy contracts are enforceable and operations can recover safely without
  content-bearing operator access.
- **NO-GO:** Spend is unbounded, deletion/export is incomplete, processing loses or
  duplicates customer work, or support depends on direct routine content inspection.

## Gate 5 — Security verification, deployment and controlled pilot readiness

### Scope and deliverables

- Independent tenant threat-model and repository-grounded security review.
- Full migration rehearsal, staging deployment in the approved region, backup/restore and
  disaster-recovery validation, and production-like proxy/storage configuration.
- Dependency/container/IaC scanning and remediation of release-blocking findings.
- Cross-browser critical-flow tests against the production container/proxy shape.
- Incident, revocation, deletion, export, tenant-leak, and provider-outage exercises.
- Controlled onboarding checklist, partner authorization, rollback, monitoring, and pilot
  stop conditions.

### Existing code that can be reused

- CI workflows, container images, Trivy/CodeQL/dependency checks, extensive backend and
  Playwright suites, readiness checks, security docs, and historical AWS design.

### Dependencies

- Gates 0-4 complete.
- Approved hosting budget/account, region, secrets, domains, certificates, storage,
  database, Redis, monitoring, backups, and incident contacts.
- Contractual authorization for any real customer data.

### Major risks

- Green CI is mistaken for production readiness.
- Historical AWS documentation is treated as evidence of a live secure deployment.
- Proxy, cookie, storage, backup, or provider configuration differs from tests.
- Security findings force redesign of tenant scope or support procedures.

### Estimate and assumptions

**10-18 person-days.** Excludes external penetration-test procurement and remediation of
unknown high-severity findings. A new cloud platform or full infrastructure-as-code build
can exceed this range.

### Acceptance criteria

- No unresolved confirmed Critical/High security findings; Medium findings have explicit
  disposition and owners.
- Migration, rollback, backup restore, revocation, retention/deletion, export, and tenant
  isolation are verified in a production-like environment.
- Exact deployed image/configuration is traceable and monitored.
- Incident contacts, stop conditions, support workflow, and customer data authorization
  are approved.
- Pilot starts with one organization at a time under bounded monitoring and rollback.

### Tests required

- Complete relevant backend/frontend/integration suites with production-like PostgreSQL,
  Redis, storage, proxy, and standalone frontend container.
- Independent cross-tenant penetration scenarios and authorization fuzzing where feasible.
- Load/cost tests at approved limits, backup/restore, migration/cutover/rollback, and chaos
  tests for provider/job/storage failures.
- Manual verification of accessibility, security headers, cookies, cache behavior, data
  residency, secrets, and operational alerts.

### Go/no-go

- **GO:** All release gates and policy evidence pass, deployment is verified, and the first
  partner has authorized controlled processing.
- **NO-GO:** Any critical isolation uncertainty, unresolved mandatory policy, unverified
  deployment, missing rollback/restore, or incident process dependent on routine operator
  content access.

## Critical path

```text
Gate 0 policy and partner evidence
  -> Gate 1 schema and safe migration
  -> Gate 2 membership/RBAC/invitations
  -> Gate 3 complete tenant isolation
  -> Gate 4 minimum required operations
  -> Gate 5 independent verification and deployment
```

Gate 0 is both the first technical dependency and the commercial kill switch. Gates 1-3
are sequential because team authorization is unsafe without a stable tenant foundation,
and shared features are unsafe without membership semantics. Gate 4 design can begin in
parallel after policies are approved, but enforcement and verification depend on the
tenant model. Gate 5 depends on the production-shaped outcome of all prior gates.

Highest-risk dependencies are complete data-ownership inventory, safe migration while
preserving user isolation, cross-tenant RAG/storage/cache coverage, revocation semantics,
deletion completeness, and a verified regional deployment.

## Work that can be deferred until after the first pilot

- Multi-organization membership and organization switching.
- Custom roles, enterprise SSO, SCIM, and delegated administration.
- Automated billing, invoices, taxes, self-service plans, and multiple pricing tiers.
- Customer-configurable retention, legal hold UI, and advanced organization lifecycle.
- Generalized operator console or break-glass content access.
- General-purpose workflow engine if bounded processing and minimal durable jobs satisfy
  approved pilot workloads.
- Broad OCR, bank aggregation, real-time ingestion, entity graph, configurable controls,
  advanced dashboards, and global/multi-region deployment.

## Proportionality review and recommendation

Team tenancy is not necessary before customer discovery. The existing single-user flow can
demonstrate the investigation concept with synthetic or contractually permitted data, and
concierge onboarding can test data compatibility and workflow value.

The proposed controlled pilot is possible for one developer but not small: **59-102
person-days** before the live pilot, plus policy, review, cloud, partner, and remediation
calendar time. That investment is disproportionate without evidence that at least two
prospects need shared team access and one has a credible paid-continuation path.

Recommended next action: complete Gate 0 only. Do not authorize Gate 1 until partner
discovery validates the team workflow and all six mandatory policy owners have approved
the decisions needed for real customer data.
