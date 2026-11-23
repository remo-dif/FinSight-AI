# Pilot Organization Tenancy and Team Authorization Capability

## Capability

- **Capability name:** Single-organization team tenancy for the controlled pilot
- **Source:** `PRODUCT-BRIEF.md`
- **Primary actors:** `organization_admin` and `reviewer`
- **Outcome after ship:** A manually provisioned team of 2-5 users can collaborate on one
  organization's investigations without cross-tenant access.
- **Success signal:** Every protected data path passes organization-isolation tests and a
  pilot team can complete a shared case workflow under approved operating policies.

## Status and scope distinctions

### Existing implemented functionality

- Users authenticate through the current access/refresh-token model.
- Transactions, cases, uploads, embeddings/RAG, document Q&A, chat, and risk signals are
  scoped to individual users.
- Case transitions, decisions, and notes have existing integrity and audit behavior.
- There is no organization, membership, invitation, or team authorization model.

### Approved pilot requirements

- One organization per user and no organization switching.
- 2-5 users per organization.
- Roles are limited to `organization_admin` and `reviewer`.
- Organizations are provisioned manually.
- Invitations provide only essential create, accept, expire, and revoke behavior.
- No automated billing, custom roles, customer-configurable retention, content-bearing
  operator console, or advanced organization lifecycle.

### Future capabilities

Multi-organization membership, organization switching, custom roles, automated billing,
advanced suspension/closure workflows, customer-configurable retention, enterprise
identity, and operator break-glass content access are deferred. They are not forbidden
permanently and must not distort the pilot implementation.

### Unresolved policies

Six policies in the final section block real customer data. Recommended options are
advice, not approved values.

## Fixed authorization and migration constraints

- Preserve all existing user-level isolation throughout migration. Organization access
  becomes additive only after the new scope is populated and verified.
- Every tenant-owned root row ultimately has one authoritative, non-null
  `organization_id`; filtering results after an unscoped query is prohibited.
- Repository queries scope by organization at the database boundary.
- Resource IDs are not authorization controls. Cross-tenant lookup returns the same
  non-disclosing result as an unavailable resource.
- A user has at most one active membership during the pilot. Organization context is
  therefore server-derived from authenticated identity and membership, not selected by a
  client header, URL, prompt, or stored browser preference.
- JWTs continue to identify the user. Organization authorization is checked against
  current database state unless an explicitly approved AUTH-01 change becomes necessary.
- The current global-looking `ADMIN` label does not grant organization or operator access.
- AI tools, RAG retrieval, citations, exports, background work, caches, and usage records
  inherit the authoritative organization scope; a model cannot choose or override it.
- Existing users receive separate migration organizations. Existing users' data is never
  silently merged.
- Initial case-decision immutability, transition/revision rules, and current audit
  guarantees remain intact.
- AUTH-01 and AUDIT-01 are protected. Any implementation change in those areas requires
  explicit approval and dedicated regression review.

## Roles and permissions

### Reviewer

- Accesses organization-scoped triage, cases, permitted documents, RAG, chat, and risk
  analysis.
- Performs the existing case actions allowed by product policy.
- Cannot invite/remove members or change roles.

### Organization administrator

- Has reviewer capabilities.
- Lists members and pending invitations.
- Invites reviewers, revokes pending invitations, and removes reviewers.
- May promote or demote another member only if the approved pilot workflow requires it;
  otherwise roles are fixed during manual provisioning.
- Cannot create custom roles, access other organizations, or grant platform-operator
  privileges.

Removing or demoting the last active organization administrator must fail safely. Routine
platform support has no customer-content permission.

## Actors and surfaces

### UI

- Invitation acceptance and clear invalid/expired/revoked states.
- Organization identity indicator without a switcher.
- Minimal admin member/invitation view.
- Existing triage, case, and evidence workspaces operating on organization-scoped data.
- Immediate loss-of-access handling that clears tenant-derived client caches, selected
  documents, case state, and AI transcripts.

### API

- Read the caller's single organization and effective role.
- List members and pending invitations for authorized admins.
- Create, accept, and revoke essential invitations.
- Remove a membership with defined revocation behavior.
- Update every existing protected domain endpoint to use organization-scoped repositories.
- Expose fixed tenant usage/limit status only where required for clear user errors.

### Manual operations

- Provision an organization and its first admin through a controlled runbook or narrowly
  scoped administrative command.
- Assign approved fixed pilot limits.
- Diagnose service health using content-free metadata, logs, metrics, and customer-supplied
  references.
- No routine operator UI or database browsing of customer content.

## States and transitions

### Organization

The pilot uses only `active`. Emergency disablement may be an infrastructure/operations
control until a separately specified lifecycle is approved. Suspension, closure, restore,
and customer-configurable lifecycle states are deferred.

### Membership

- `invited -> active`
- `invited -> revoked|expired`
- `active -> removed`

`removed`, `revoked`, and `expired` are terminal audit states. A user cannot have two
active pilot memberships.

### Invitation

- `pending -> accepted`
- `pending -> revoked|expired`

Acceptance must atomically validate the hashed single-use token, email binding,
organization, seat limit, existing membership, and expiry before creating one active
membership and consuming the invitation.

## Interface and failure contract

### Inputs and outputs

- Identity comes from the existing authenticated session.
- Organization and role come from an active membership resolved server-side.
- Invitation creation accepts normalized email, one of two roles, expiry, and an
  idempotency key.
- Responses expose only minimal organization and effective-role information.
- Stable non-sensitive errors cover no membership, inactive membership, invitation state,
  seat/usage denial, and unavailable resources.

### Concurrency, recovery, and idempotency

- Duplicate invite creation is idempotent and cannot create duplicate active membership.
- Concurrent acceptance permits one success and deterministic subsequent responses.
- Membership uniqueness enforces one organization per user during the pilot.
- Membership removal and role changes use revision/CAS or an equivalent lost-update
  defense.
- The last-admin invariant is enforced transactionally.
- Partial data migration stops with a resumable journal; requests cannot observe ambiguous
  tenant ownership.
- Failed or stale authorization clears tenant-derived frontend state before reauthentication.

## Data implications

### New sources of truth

- `organizations`: minimal identity, provisioning metadata, and fixed pilot policy
  references; no advanced lifecycle abstraction.
- `organization_memberships`: user, organization, one of two roles, status, and revision.
- `organization_invites`: organization, bound email, role, hashed token, status, expiry,
  and idempotency/audit metadata.

### Scope propagation

The design review must trace transactions; cases and all children; uploads and object
storage keys; embeddings and retrieval; document-Q&A sources/citations; chat sessions and
messages; risk analysis inputs/outputs; audit tenant attribution; usage/limit records;
jobs; caches; and exports. Child rows may inherit scope through a required parent only if
all access paths join through that parent under the same organization predicate and
database constraints prevent cross-tenant parentage.

### Migration sequence

1. Create one private migration organization and admin membership per existing user.
2. Add nullable organization references without changing current authorization.
3. Backfill tenant roots in bounded, restartable batches; propagate/validate children.
4. Reconcile row, object, embedding, and audit counts and detect orphan/cross-owner data.
5. Add database constraints and organization-scoped repository paths while retaining
   user predicates during the compatibility phase.
6. Cut over only after isolation tests and migration verification pass.
7. Remove transitional user predicates only in a later explicit gate after proving the
   organization boundary is complete.

No migration combines existing users or infers shared organizations from email domains,
roles, case assignment, filenames, or similar heuristics.

## Security and policy requirements

- Threat-model IDOR, invitation theft/replay, email enumeration, membership races,
  last-admin removal, stale browser state, cross-tenant RAG/citation leakage, background
  jobs, caches, exports, logs, and privileged infrastructure access.
- Test list/detail/mutation and indirect child paths for every domain with two organizations
  and adversarial identifiers.
- Use tenant-aware storage paths, cache keys, job payloads, provider cost journals, and
  observability dimensions.
- Apply IP/account abuse controls plus organization-level quotas once policy values are
  approved.
- Never log raw invitation tokens, JWTs, prompts, document text, or customer export data.
- PostgreSQL row-level security may be evaluated as defense in depth; it cannot replace
  repository and service authorization.
- Operator support must use metadata and customer-mediated evidence by default. Any future
  break-glass content access requires a separate policy, implementation, and audit gate.

## Mandatory unresolved policies

No recommendation below is approved policy. Decision owners must record exact values and
procedures before the indicated gate.

### 1. Data retention period and deletion SLA

- **Recommended option:** One fixed pilot-wide retention schedule, contractually stated,
  with a bounded deletion SLA covering database rows, object storage, embeddings, caches,
  jobs, exports, and applicable provider artifacts.
- **Alternatives:** Retain until customer request; immediate deletion on membership or
  contract end; customer-configurable schedules; indefinite retention.
- **Trade-offs:** A fixed schedule is simpler and testable but may not fit every partner.
  Customer configuration adds product, legal, scheduling, and verification complexity.
- **Security implications:** Excess retention increases breach impact; premature deletion
  can destroy audit evidence. Legal hold and backups must be addressed explicitly.
- **Operational implications:** Requires inventory, deletion orchestration, retry,
  verification, exception reporting, backup treatment, and customer communication.
- **Decision owner:** Product owner with legal/privacy and security review.
- **Blocking effect:** Blocks deployment design finalization and all real customer data;
  does not block customer discovery or schema prototyping with synthetic data.

### 2. Data residency region

- **Recommended option:** Select one fixed deployment and storage region for the pilot,
  agreed with every design partner; keep all primary data, objects, logs, backups, and
  processing there where provider capabilities allow.
- **Alternatives:** Customer-selected regions; multi-region replication; no contractual
  residency commitment.
- **Trade-offs:** One region minimizes cost and operational complexity but narrows eligible
  customers. Multi-region increases availability and sales reach at substantial cost.
- **Security implications:** Region mismatch can violate customer or regulatory
  obligations; logs, backups, AI providers, and support tooling can create hidden transfers.
- **Operational implications:** Determines cloud/provider selection, disaster recovery,
  backup placement, monitoring, subprocessors, and deployment runbooks.
- **Decision owner:** Product owner with legal/privacy, security, and infrastructure owner.
- **Blocking effect:** Blocks production infrastructure/deployment and real customer data;
  not local development with synthetic data.

### 3. Maximum membership revocation propagation time

- **Recommended option:** Define a short, measurable maximum and enforce database
  membership checks on protected requests, with cache invalidation and session/client-state
  clearing; do not encode durable tenant permission solely in JWT claims.
- **Alternatives:** Immediate access-token/family revocation; accept access-token lifetime;
  short-lived cached membership; manual account disablement.
- **Trade-offs:** Per-request validation gives prompt revocation and simple semantics but
  adds database/cache load. Token-only permission is faster but remains stale.
- **Security implications:** The maximum bounds continued access by a removed user and must
  cover APIs, SSR, jobs, downloads, caches, and active AI work.
- **Operational implications:** Requires measurable revocation tests, cache strategy,
  failure behavior, incident runbooks, and monitoring.
- **Decision owner:** Security owner and product owner, with backend/auth maintainers.
- **Blocking effect:** Blocks membership implementation acceptance, deployment, and real
  customer data. AUTH-01 changes, if any, require separate approval.

### 4. Case/audit export format and availability

- **Recommended option:** A user-initiated, organization-scoped export with a documented
  machine-readable manifest plus human-readable case summary, integrity metadata, bounded
  availability, and authenticated download.
- **Alternatives:** CSV/JSON only; PDF only; manual customer-request export; no pilot export.
- **Trade-offs:** Dual output improves portability and review but costs more to specify and
  test. Manual export reduces automation but conflicts with no routine operator content
  access unless performed through customer-controlled tooling.
- **Security implications:** Exports concentrate sensitive data and require authorization,
  non-guessable references, expiry, encryption, audit, and deletion.
- **Operational implications:** Requires generation/retry, storage, expiry cleanup,
  versioning, support documentation, and verification of completeness.
- **Decision owner:** Product owner with customer/design-partner, security, and legal input.
- **Blocking effect:** Exact format blocks export development. An approved availability
  policy blocks pilot deployment and real data if export is contractually or legally
  required.

### 5. Storage, upload, seat, and AI usage limits

- **Recommended option:** One fixed pilot plan with explicit hard limits and clear user
  errors; values are approved from partner workload evidence and provider cost modelling.
- **Alternatives:** Soft alerts only; per-customer manual limits; unlimited fair use;
  automated metered tiers.
- **Trade-offs:** Fixed hard limits control abuse and spend but can interrupt investigations.
  Manual exceptions are flexible but operationally inconsistent. Metering tiers are
  premature without pricing evidence.
- **Security implications:** Limits reduce denial-of-wallet, parser abuse, storage
  exhaustion, and distributed account abuse; they must not leak tenant usage.
- **Operational implications:** Requires tenant attribution, atomic accounting,
  reservation/reconciliation for AI cost, dashboards/alerts, and an exception runbook.
- **Decision owner:** Product/business owner with engineering/operations and security.
- **Blocking effect:** Values block Gate 4 enforcement, cost-controlled deployment, and real
  customer data; counters can be designed earlier using synthetic limits.

### 6. Support and incident response without routine content access

- **Recommended option:** Metadata-first support with customer-mediated reproduction or
  export, documented severity/escalation paths, and infrastructure-level emergency
  containment. No standing operator permission to customer content.
- **Alternatives:** Customer screen-share only; encrypted customer-submitted support bundle;
  separately approved time-bound break-glass access; standing operator access.
- **Trade-offs:** No routine access minimizes insider risk but increases resolution time.
  Break-glass can accelerate severe incidents but requires strong approval, audit, and
  notification controls.
- **Security implications:** Must address privileged infrastructure access, log hygiene,
  evidence custody, breach notification, credential compromise, and tenant containment.
- **Operational implications:** Requires on-call ownership, contact routes, triage and
  containment runbooks, evidence collection, post-incident review, and partner exercises.
- **Decision owner:** Security/incident owner with product, legal/privacy, and operations.
- **Blocking effect:** Blocks controlled pilot readiness and all real customer data; does
  not block feature development with synthetic data.

## Non-goals

- Multi-organization membership or organization switching.
- Custom roles, SSO, SCIM, or cross-organization collaboration.
- Automated billing or plan lifecycle.
- Customer-configurable retention or advanced organization lifecycle.
- Routine operator content access or a platform-superadmin hidden in the current `ADMIN`.
- Autonomous fraud decisions, payment blocking, bank aggregation, or broad integrations.

## Handoff

- **Ready for implementation?** No. Gate 0 must produce approved policy records and design
  partner evidence that team collaboration is necessary.
- **Needs architecture review?** Yes: schema ownership, migration, repository scope,
  revocation, invitation concurrency, jobs/caches, exports, and deployment boundaries.
- **Needs product clarification?** Yes: the six mandatory policies require decision-owner
  approval; proposed options are not approved values.
- **Next lane after Gate 0 approval:** architecture decision records and a test-first
  delivery plan for Gate 1.
