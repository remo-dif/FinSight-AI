# FinSight-AI Micro-SaaS Product Brief

## Decision

**Conditional GO: validate as a narrow, design-partner B2B pilot before building a
self-service SaaS.**

The repository already supports a credible investigation loop: authenticated ingestion,
user-scoped cases and documents, explainable risk signals, auditable decisions, and
grounded document Q&A. It does not yet support the commercial and operational contract of
a multi-tenant SaaS. The next milestone should prove that a small fraud-operations team
will repeatedly use this workflow on real, permitted data. Billing, broad integrations,
and a public launch should follow that evidence, not precede it.

## 1. Who this is for

The initial customer is a **fraud or payment-operations lead at a small regulated fintech,
payment provider, marketplace, or specialist consultancy** with roughly 2-10 reviewers.
They receive transaction exports and supporting documents, but lack the volume or budget
for an enterprise fraud platform and currently coordinate investigations through CSVs,
shared folders, spreadsheets, and ticketing tools.

This is not initially for retail consumers, banks with established detection stacks, or
teams requiring real-time payment blocking.

## 2. Pain and current workaround

The target team repeatedly has to:

1. assemble transaction and document evidence from disconnected files;
2. explain why an item was flagged;
3. record a defensible decision and follow-up notes;
4. avoid leaking one customer's evidence into another investigation;
5. reproduce the reasoning later for internal review.

The repository demonstrates these mechanics, but the frequency, cost, and willingness to
pay are not yet evidenced by users or revenue. Customer discovery must quantify cases per
week, minutes per case, rework rate, audit preparation effort, and current tool spend.

## 3. Why now

- Smaller teams want AI assistance but cannot accept opaque autonomous decisions.
- FinSight-AI's deterministic tool boundary, validated citations, ownership checks, and
  audit trail align with a human-in-the-loop adoption path.
- The existing code can support an assisted pilot without first building real-time bank
  connectivity or an autonomous fraud engine.

The opportunity is workflow compression and evidence quality, not a claim of superior
fraud-detection accuracy.

## 4. Ten-star version

A reviewer opens a tenant-isolated queue populated from existing payment and document
sources, sees calibrated and explainable signals, assembles evidence with an AI copilot,
records a policy-compliant decision, and exports a complete audit package. Team leads can
assign work, configure policies, measure handling time and outcomes, and integrate the
workflow with their case-management and data systems.

## 5. Pilot MVP

The smallest pilot that tests the thesis is:

- one organization with 2-5 invited reviewers;
- explicit organization membership and tenant-scoped authorization;
- CSV transaction ingestion plus text-PDF evidence;
- bounded, explainable risk signals and a review queue;
- case assignment, notes, decision history, and closure;
- grounded Q&A over explicitly selected owned documents;
- an exportable case summary and audit history;
- background processing with visible job state and safe retry;
- basic operational telemetry, usage limits, retention controls, and admin support tools;
- a manually provisioned plan with usage metering, without self-service billing.

The current code supplies much of the investigation core. The missing pilot-critical
capabilities are organization tenancy, invitations/RBAC, asynchronous ingestion,
production observability, retention/export controls, and a verified deployment.

## 6. Anti-goals

The pilot will not include:

- autonomous fraud determinations or automatic payment blocking;
- measured fraud-detection claims without a representative labelled dataset;
- bank aggregation or broad third-party integrations;
- OCR for every document type;
- graph intelligence, configurable controls, or data workspaces merely because navigation
  placeholders exist;
- enterprise SSO, custom model hosting, mobile-native applications, or global deployment;
- self-service pricing and billing before repeat usage is demonstrated;
- compliance certification claims.

## 7. Success criteria

Run a 4-6 week pilot with at least two design partners. Continue investment only if:

- at least 3 reviewers complete 20 or more real permitted cases each;
- median time from import to first review-ready case is under 10 minutes;
- median active handling time improves by at least 30% against the customer's baseline;
- at least 70% of opened cases reach a recorded decision in FinSight-AI;
- at least 50% of weekly active reviewers return in three separate weeks;
- zero cross-tenant disclosure or unauthorized evidence access occurs;
- at least one partner commits to a paid continuation or signed pilot extension.

Guardrails: track AI correction/rejection rate, unsupported-answer rate, ingestion failure
rate, p95 job duration, support interventions, provider cost per completed case, and every
authorization or retention incident.

## Repository-grounded readiness

### Strong foundations

- Modular Next.js/FastAPI/PostgreSQL architecture with migrations and CI.
- Rotating refresh-token families, scoped queries, rate limiting, and security regression
  coverage.
- User-scoped transactions, uploads, RAG retrieval, cases, and risk signals.
- Explainable deterministic indicators and application-controlled AI tool execution.
- Auditable case workflow and validated document citations.
- Container builds, security scans, and immutable image publication.

### Blocking gaps for a paid pilot

- No organization or tenant membership model; current ownership is individual-user based.
- No invitation flow or reliable analyst/admin team RBAC.
- No verified live hosting environment or production operations evidence.
- Upload extraction and embeddings remain request-bound; no durable worker/job contract.
- No email ownership verification, password reset, or operator-grade account recovery.
- No customer-facing retention, deletion, or case-export workflow.
- No full tracing, alerting, support console, or tenant-level usage/cost controls.
- No evidence of user demand, retention, pricing acceptance, or live-model quality on a
  representative customer dataset.

### Non-blocking until after pilot evidence

- Automated subscriptions and invoicing.
- Open-banking connectivity and real-time event ingestion.
- OCR breadth and institution-specific parsers beyond pilot inputs.
- Entity graph and configurable policy workspaces.
- Enterprise SSO and advanced reporting.

## Founder review score

| Signal | Score | Evidence |
| --- | ---: | --- |
| Problem clarity | 7/10 | The investigation workflow and safety boundaries are explicit. |
| Product completeness | 5/10 | Core loop exists; team and operational capabilities do not. |
| Usage/retention evidence | 0/10 | No production users or cohort evidence in the repository. |
| Revenue evidence | 0/10 | No pricing, contracts, billing, or paid pilots. |
| Technical defensibility | 6/10 | Trust-oriented evidence and authorization design are useful but copyable. |
| Distribution advantage | 1/10 | No demonstrated acquisition channel or partner pipeline. |
| Overall readiness | 4/10 | Ready for discovery and a controlled pilot build, not public SaaS launch. |

## The one move with the highest leverage

Recruit two design partners and run the existing workflow manually with representative,
contractually permitted CSV/PDF inputs before expanding the feature surface. The product
thesis is validated only if reviewers repeatedly complete cases faster and trust the
evidence trail enough to pay.

## Next decision gate

Proceed to an implementation-ready capability plan only after confirming:

1. a named initial customer segment;
2. two reachable design partners;
3. their weekly case volume and current handling-time baseline;
4. required roles, retention period, data region, and deployment constraints;
5. a pilot price or explicit paid-continuation criterion.

If these cannot be established, stop commercial feature work and retain FinSight-AI as a
portfolio/reference implementation.
