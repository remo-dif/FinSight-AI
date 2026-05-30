# 20. Production Roadmap

## Phase 1

- Harden auth flows with refresh token rotation persistence.
- Add migrations for all database tables.
- Add institution-specific CSV import profiles.
- Add OpenTelemetry traces and structured log correlation IDs.

## Phase 2

- User correction loop for categories.
- Document parser evaluation dataset.
- Row-level encryption for sensitive document text.
- Background workers for OCR and embeddings.

## Phase 3

- Bank aggregation integration.
- Organization accounts and team RBAC.
- Scheduled reports and alerts.
- Deployment to managed Postgres, container platform, object storage, and secret manager.

## Reviewer Validation

The current foundation demonstrates senior AI engineering architecture. Before real customer use, the highest-priority gaps are migration rigor, encryption at rest strategy, production secret management, rate limit storage, and independent security review.
