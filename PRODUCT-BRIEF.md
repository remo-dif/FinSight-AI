# FinSight-AI Micro-SaaS Product Brief

## Decision

**Conditional GO for a narrowly scoped, team-based B2B pilot.**

FinSight-AI targets small professional fraud-investigation and payment-operations teams.
The pilot supports one organization per user, 2-5 users per organization, and only the
`organization_admin` and `reviewer` roles. It is a controlled design-partner pilot, not a
self-service SaaS launch or a claim of production readiness.

This direction is a commercial hypothesis. Team tenancy is not required to interview
customers or demonstrate the existing single-user workflow. Engineering should not begin
until customer discovery confirms that shared queues and evidence are important enough to
justify the additional authorization and migration risk.

## Evidence classification

### Verified repository facts

- Authentication, rotating refresh-token families, user-scoped transactions, uploads,
  cases, RAG retrieval, document Q&A, chat, and risk signals exist.
- Case decisions and transitions are auditable, but current ownership is individual-user
  based and the repository has no reliable tenant membership model.
- Risk signals are explainable heuristics; they do not determine fraud or demonstrate
  measured detection accuracy.
- Upload extraction and embedding are request-bound; there is no durable production job
  workflow.
- CI, container builds, and security checks exist. There is no currently verified live
  production environment.
- No organization provisioning, invitations, team RBAC, automated billing, customer
  retention controls, or customer-facing case/audit export is implemented.

### Estimates

The effort ranges and sequencing are documented in
`docs/product/micro-saas-implementation-gates.md`. They are engineering estimates, not
delivery commitments.

### Commercial hypotheses

- Small professional teams will pay for a shared, explainable investigation workflow.
- Shared evidence and audit history reduce handling time and rework enough to justify a
  dedicated product.
- CSV and text-PDF inputs are sufficient for an initial pilot.
- Two design partners can be recruited without first building team tenancy.

None of these hypotheses is demonstrated by repository code or automated tests.

## Target customer and problem

The initial customer is a fraud or payment-operations lead at a small fintech, payment
provider, marketplace, or specialist consultancy with 2-5 reviewers. The team currently
assembles transaction and document evidence across CSV files, shared folders,
spreadsheets, and ticketing tools, then records and reconstructs investigation decisions
manually.

The product promise is a secure, shared investigation workflow with explainable signals,
grounded evidence, and an auditable decision history. It is not real-time fraud prevention,
autonomous decisioning, or a substitute for a customer's compliance program.

## Approved pilot requirements

- One manually provisioned organization per user; a user cannot switch organizations.
- 2-5 users per organization.
- Exactly two roles: `organization_admin` and `reviewer`.
- Essential invitation creation, acceptance, expiry, and revocation.
- Organization-scoped transactions, cases, notes, decisions, uploads, embeddings, RAG,
  chat, risk analysis, audit attribution, and exports.
- CSV transaction ingestion and text-PDF evidence; current image metadata behavior remains
  accurately described and OCR is not promised.
- Shared triage, case review, evidence, and grounded document Q&A.
- Manual plan and organization administration without routine operator access to customer
  content.
- Fixed platform policies and limits for the pilot once approved; customers do not
  configure retention or custom roles.
- A verified deployment and controlled onboarding process before real customer data.

## Concierge-first validation

Before building team tenancy, run customer discovery and a no-customer-data or explicitly
authorized demonstration of the existing workflow. Manual steps may replace automation:

- founder-led organization and account setup;
- manually agreed CSV/PDF templates;
- manually scheduled onboarding and support;
- manually assigned plan limits;
- human-reviewed case/audit export generation during validation, using synthetic or
  contractually permitted data and without granting routine operator content access.

Concierge operation can defer billing, generalized configuration, an operator console,
and broad ingestion automation. It cannot replace tenant isolation, access revocation,
retention/deletion enforcement, incident response, or verified deployment when real
customer data is processed.

## Mandatory policy decisions before real customer data

The following remain unresolved and block controlled use of real customer data:

1. data retention period and deletion SLA;
2. data residency region;
3. maximum membership revocation propagation time;
4. case/audit export format and availability;
5. storage, upload, seat, and AI usage limits;
6. support and incident-response procedures without routine operator content access.

Recommended options, alternatives, trade-offs, owners, and exact blocking effects are in
`docs/product/organization-tenancy-capability.md`. Recommendations are not approved
policy values.

## Pilot success criteria

Run a 4-6 week controlled pilot with at least two design partners only after the mandatory
policies and security/deployment gates are satisfied. Continue investment only if:

- at least 3 reviewers complete 20 or more permitted cases each;
- median import-to-review-ready time is under 10 minutes;
- median active handling time improves by at least 30% from the partner's measured
  baseline;
- at least 70% of opened cases reach a recorded decision in FinSight-AI;
- at least 50% of weekly active reviewers return in three separate weeks;
- no cross-tenant disclosure or unauthorized evidence access occurs;
- at least one partner commits to a paid continuation or signed extension.

Track AI correction/rejection rate, unsupported-answer rate, ingestion failure rate, p95
processing duration, support interventions, provider cost per completed case, and every
authorization, retention, or deletion incident. These thresholds are proposed validation
criteria, not evidence already achieved.

## Pilot anti-goals

- Organization switching or membership in multiple organizations.
- Custom roles, enterprise SSO, SCIM, or directory synchronization.
- Automated billing, invoicing, taxes, or self-service plan changes.
- Customer-configurable retention or advanced organization lifecycle management.
- Routine operator access to customer content or a content-bearing operator console.
- Autonomous fraud determinations or payment blocking.
- Bank aggregation, broad third-party integrations, or real-time event ingestion.
- General OCR, entity-graph intelligence, configurable policy workspaces, or global
  deployment.
- Compliance certification or measured fraud-detection claims.

## Future capabilities, explicitly deferred

- Multi-organization membership and organization switching.
- Custom permissions and larger teams.
- Automated subscription lifecycle and billing.
- Customer-configurable retention, legal hold, and regional placement.
- Just-in-time break-glass support access, if later justified and separately approved.
- Open-banking connectivity, broader parsers, OCR, graph analysis, and advanced reporting.

Deferral is not a permanent architectural prohibition. The pilot schema and APIs must
avoid assumptions that make future migration unnecessarily destructive.

## Readiness and critical challenge

The repository has a strong investigation core, but the collaboration model is not yet
implemented. Existing case assignment does not establish team authorization, and the
current risk model provides review indicators rather than a shared detection pipeline.

For one developer, the complete pilot foundation is a multi-month effort. Building it
before customer discovery is disproportionate to the currently unvalidated commercial
opportunity. The correct sequence is:

1. resolve Gate 0 policies and recruit qualified design partners;
2. validate the existing workflow with synthetic or contractually permitted inputs;
3. obtain explicit evidence that team collaboration is required;
4. only then authorize organization-tenancy implementation.

If partner discovery does not confirm recurring team usage and willingness to pay, stop
commercial feature work and retain FinSight-AI as a portfolio/reference implementation or
re-scope it to a single-user product.
