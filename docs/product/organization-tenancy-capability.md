# Organization Tenancy and Multi-User Authorization Capability

## Capability

- **Capability name:** Organization tenancy and multi-user authorization
- **Source:** `PRODUCT-BRIEF.md` Micro-SaaS pilot decision
- **Primary actor:** An invited fraud or payment-operations reviewer
- **Outcome after ship:** A small customer team can collaborate inside one organization
  without any member being able to read or mutate another organization's data.
- **Success signal:** A 2-5 person pilot team can be provisioned, complete shared case
  reviews, and pass automated cross-tenant isolation tests for every protected resource.

## Product Intent

FinSight-AI will allow a small operations team to share an organization-scoped queue,
documents, cases, and investigation history. Membership and role determine access;
possession of a resource identifier, an existing individual-user record, or the current
`ADMIN` label never grants cross-organization access. The user-visible promise is secure
collaboration on shared investigations, not enterprise identity management.

## Constraints

### Fixed rules and invariants

- Every tenant-owned row has one authoritative `organization_id`; tenant ownership must
  not be inferred through a nullable or optional join at authorization time.
- Every authenticated tenant request resolves an active user, an active organization,
  and an active membership before accessing tenant data.
- Repository queries must scope by `organization_id` at the database boundary. Filtering
  serialized results after an unscoped query is prohibited.
- Resource identifiers remain globally unique and unguessability is not an authorization
  control.
- A user without an active membership receives no tenant data, including through RAG,
  document citations, case notes, exports, audit views, or AI tool results.
- The existing individual ownership guarantees cannot be weakened during migration.
- Initial case decisions remain immutable and existing case transition/revision rules
  continue to apply.
- AI retrieval and tool execution inherit the same organization scope as the initiating
  request. The model never selects or overrides tenant context.
- Organization context is server-derived. A client-supplied organization ID is only a
  selector and must be checked against active membership.
- Authorization failures must not reveal whether a resource exists in another tenant.
- Membership, role, invitation, and organization-context changes are security-relevant
  operations and require audit events without secrets or document content.
- Tenant migration must be reversible before destructive cleanup and must not silently
  merge data belonging to different existing users.
- AUTH-01 and AUDIT-01 remain protected areas; implementation affecting them requires an
  explicit review/approval gate.

### Scope boundaries for the pilot

- One pilot organization contains 2-5 human reviewers.
- Collaboration covers transactions, cases, notes, decisions, uploads, embeddings,
  document Q&A, chat sessions, risk signals, and exports derived from those resources.
- Provisioning and plan assignment may be operator-assisted.
- Email/password authentication remains the supported identity mechanism for the pilot.
- Tenant-level usage limits are required, but automated charging is not.

### Architecture preferences, not yet product policy

- Prefer explicit `organizations`, `organization_memberships`, and `organization_invites`
  entities over adding a role directly to `users`.
- Prefer one active organization in the browser session with an explicit context switch
  if multi-organization membership is allowed.
- Prefer opaque, single-use, expiring invitation tokens stored only as hashes.
- Prefer database constraints and tenant-scoped repository APIs in addition to route
  dependencies; PostgreSQL row-level security may be evaluated as defense in depth, not
  as a substitute for application authorization.

## Actors and Surfaces

### Actors

- **Reviewer:** Reads the shared queue and evidence, adds notes, and performs allowed case
  transitions and decisions.
- **Organization administrator:** Invites/removes members and manages pilot-level team
  settings. This role does not imply platform-wide or cross-tenant access.
- **Platform operator:** Provisions pilot organizations and handles support through
  separately controlled operational procedures. Operator access is not provided by the
  current application `ADMIN` role.
- **Invited user:** Can inspect and accept or reject a valid invitation, but cannot access
  tenant data before acceptance and authentication.

### UI surfaces

- Organization bootstrap or invitation-acceptance flow.
- Current-organization indicator and, only if allowed, organization switcher.
- Member list, pending invitations, role changes, and removal controls.
- Shared triage, cases, and evidence workspaces scoped to the active organization.
- Clear loss-of-access and stale-context recovery states.

### API surfaces

- Organization and active-context discovery.
- Membership list and permitted role updates.
- Invitation create, inspect, accept, revoke, and resend operations.
- Existing transaction, case, upload, chat, document-Q&A, and risk endpoints updated to
  use a required organization authorization context.
- Tenant usage summary for enforcement and operator support.

### Operator and reporting surfaces

- Manually provision and suspend a pilot organization.
- Inspect sanitized organization status, membership count, usage limits, and job health.
- Export organization-scoped audit/case information through a separately authorized path.

## States and Transitions

### Organization

- `active -> suspended -> active`
- `active|suspended -> closure_pending -> closed`
- `closed` is terminal; retention/deletion work may continue asynchronously.

Suspension blocks new tenant work and data mutation. The exact read/export policy during
suspension is an open product decision.

### Membership

- `invited -> active`
- `invited -> revoked|expired`
- `active -> suspended -> active`
- `active|suspended -> removed`

`removed`, `revoked`, and `expired` are terminal records retained for audit. Removing the
last organization administrator must be rejected or completed through an explicit
operator recovery procedure.

### Invitation

- `pending -> accepted`
- `pending -> revoked|expired`

Acceptance is atomic: validate token, email binding, organization state, seat/usage policy,
and existing membership, then create or activate exactly one membership and consume the
invitation.

### Active organization context

- `unselected -> selected`
- `selected(A) -> selected(B)` only after membership validation
- `selected -> invalidated` on membership removal, organization suspension, or stale
  session context

Context invalidation must clear organization-derived frontend caches, selected documents,
case state, and AI transcripts before another tenant can become active.

## Interface Contract

### Inputs

- Authenticated identity and refresh-family/session context.
- Server-validated organization selector.
- Membership role and status.
- Invitation email, requested role, expiry, and idempotency key.
- Existing resource identifiers, always resolved inside organization scope.

### Outputs

- Minimal organization identity and the caller's effective membership permissions.
- Invitation status without returning token hashes or enumerating unrelated accounts.
- Existing domain responses containing only active-organization resources.
- Stable, non-sensitive error codes for missing context, inactive membership, suspended
  organization, expired invitation, and policy-limit denial.

### Required side effects

- Audit organization, membership, role, invite, suspension, and context-security events.
- Invalidate affected server/client caches when organization or membership state changes.
- Revoke or otherwise make unusable tenant authorization derived from a removed or
  suspended membership within a defined maximum propagation time.
- Attribute usage and AI/provider cost reservations to the authoritative organization.

### Failure states and recovery

- Duplicate invitation requests are idempotent and never create duplicate active
  memberships.
- Concurrent acceptance permits one success and deterministic subsequent responses.
- Last-admin removal fails safely.
- A suspended tenant cannot start uploads, embeddings, chats, exports, or case mutations.
- A failed context switch retains no target-tenant data and does not erase unrelated
  persisted work without an explicit user-facing recovery path.
- Partial tenant migration stops with a resumable journal; no request may observe a row
  whose tenant ownership is ambiguous.

### Idempotency and concurrency

- Invite creation, acceptance, revocation, role change, membership removal, organization
  suspension, and migration batches require explicit idempotency/concurrency semantics.
- Membership and organization updates use a revision or compare-and-swap contract.
- Database uniqueness prevents duplicate membership for one user and organization and
  duplicate live invitation policy violations.

## Data Implications

### Sources of truth

- `organizations`: tenant lifecycle and pilot policy state.
- `organization_memberships`: user-to-organization authorization and role state.
- `organization_invites`: invitation lifecycle and hashed credential material.
- Tenant-owned domain tables: explicit authoritative `organization_id`.

### Ownership propagation

At minimum, transactions, cases, case notes/decisions/assignments, uploads, embeddings,
chat sessions/messages, risk artifacts if persisted, export jobs, usage records, and audit
event tenant attribution must be reviewed. A child row may inherit tenant identity through
a required parent only when every access path joins the parent under the same tenant
predicate and database constraints prevent cross-tenant parentage.

### Migration

- Existing users and their data need a deterministic mapping to private legacy
  organizations or another explicitly approved ownership model.
- Backfill organization IDs before making them required, verify counts and foreign-key
  consistency, then enforce non-null and uniqueness constraints.
- Do not combine two existing users' data into a shared organization automatically.
- Provide preflight, batched migration, verification, rollback, and cutover steps.
- Legacy API clients require a documented context-selection transition or a versioned
  compatibility window; implicit permanent fallback is not acceptable.

### Retention and deletion

Retention duration, legal hold, customer export window, tombstone policy, and deletion
SLA are unresolved. Deletion must cover relational data, object storage, embeddings,
caches, queued work, derived exports, and provider-side artifacts where applicable.

## Security and Policy

- Threat-model IDOR, confused deputy, stale browser state, invitation theft/replay,
  membership races, last-admin lockout, tenant suspension bypass, cross-tenant RAG
  retrieval, export leakage, and privileged operator abuse.
- Create a tenant-isolation regression matrix covering list/detail/mutation endpoints,
  indirect child resources, search/retrieval, AI citations/tools, jobs, and exports.
- Never trust organization IDs embedded in AI prompts, document metadata, filenames, or
  client caches.
- Rate limits and cost budgets need both client-abuse controls and organization-level
  quotas.
- Invitation and membership endpoints require anti-enumeration behavior and targeted
  abuse controls.
- Logs, traces, metrics, error reporting, and support tooling must not include raw tokens,
  prompts, document text, or cross-tenant identifiers beyond approved pseudonymous keys.
- A platform operator access model, if introduced, requires separate just-in-time access,
  reason capture, and audit design; it is not part of ordinary tenant RBAC.

## Non-Goals

- Billing checkout, invoicing, taxes, or automated subscription lifecycle.
- Enterprise SSO, SCIM, directory sync, or custom roles.
- Cross-organization collaboration or shared cases.
- Autonomous fraud decisions or payment blocking.
- Bank aggregation, real-time transaction ingestion, or broad external integrations.
- A global platform-superadmin capability hidden inside the current `ADMIN` role.
- Retrofitting unrelated Graph, Data, or Controls placeholder workspaces.

## Open Questions

The following decisions block implementation and must not be inferred from the current
repository:

1. Can one user belong to multiple organizations during the pilot, or exactly one?
2. Are the pilot roles only `organization_admin` and `reviewer`, and which case actions
   differ between them?
3. Who may invite the first and subsequent members, and is verified email ownership
   required before invitation acceptance?
4. What happens to read/export access when an organization is suspended?
5. What are the retention period, deletion SLA, legal-hold behavior, and customer export
   format?
6. Is data residency constrained to a specific region for the initial design partners?
7. What tenant usage limits apply to seats, storage, uploads, AI tokens/cost, and cases?
8. How quickly must membership removal invalidate already-issued access tokens?
9. Which existing-user migration behavior is acceptable for local/demo and future hosted
   data?
10. Is a platform support operator allowed to access customer content, and under what
    approval/evidence contract?

## Handoff

- **Ready for implementation?** No. The cross-cutting authorization and migration design
  must not begin until the blocking product decisions above are resolved.
- **Needs architecture review?** Yes. Review schema ownership, request context, repository
  contracts, token/session invalidation, migration sequencing, and defense-in-depth.
- **Needs product clarification?** Yes. Roles, membership cardinality, suspension,
  retention, region, limits, and support access are product policy.
- **Next ECC lane:** `architecture-decision-records`, followed by `project-flow-ops` and a
  test-first implementation plan after approval.
