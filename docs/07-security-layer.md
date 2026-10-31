# 14. Security Layer

## Controls Implemented

- JWT access tokens and persisted, hashed refresh-token families with one-use rotation, replay detection and family-scoped revocation. Already issued access JWTs remain valid until expiry.
- bcrypt passwords: registration minimum 10 characters, both auth requests maximum 72 UTF-8 bytes, no truncation or normalization. No public password-change/reset endpoint exists.
- Authenticated ownership checks; role dependencies restrict uploads to user/admin roles. This is not a complete analyst-role authorization model.
- Secure upload validation for extension, MIME type, size, and path isolation.
- Audit logging model for auth, upload, and AI tool actions.
- Per-IP general/login budgets and a temporary HMAC account-identifier login quota; Redis is required in production. Development memory limits are per process, not a Redis outage fallback.
- Auth validation errors omit submitted inputs, while retaining actionable 422 messages. OpenAPI describes bearer tokens obtained from JSON login, not an unsupported OAuth2 form endpoint.
- CORS restricted by environment variable.

## Threat Model

- Malicious upload: reject unsupported type, cap size, isolate storage path, parse through controlled services.
- Financial labels and model selections: deterministic evidence validation and formatting constrain financial claims. This is not a general document prompt-injection security guarantee.
- Data exfiltration through chat: the application runs user-scoped tools; the LLM selects allowed financial claim IDs and has no direct SQL/tool-calling access. Authenticated document Q&A is exposed with owned-document scope and citation-reference validation, but does not verify semantic support (`grounded=false`) or guarantee resistance to document prompt injection.
- Token compromise: short-lived access tokens, rotated persisted refresh tokens, generic login failures and dummy bcrypt verification. Registration returns the same HTTP 202 acknowledgement for new and existing accounts. No email ownership verification exists, so register-then-login enumeration remains possible. Account quotas expire without permanent lockouts but can still be targeted for temporary denial.

## Production Hardening

- Add object storage malware scanning.
- Verify production S3 encryption/IAM and optional customer KMS configuration; no blanket at-rest encryption claim is made for extracted database text.
- Verify actual trusted proxy CIDRs, forwarding behavior and origin restrictions before relying on viewer IP identity.
- Review reused upload volume permissions for non-root UID/GID 10001; do not automatically chown or delete existing data.
- Add SIEM export for audit logs.

Redis errors fail closed with HTTP 503, without memory fallback. Rate exhaustion
returns 429. Memory sliding windows expire attempts aged at least 60 seconds;
Redis uses fixed minute windows with expiring keys. Accepted attempts count even
when the downstream handler returns 401 or 422. See the policy and remaining limits
in [the consistency report](25-api-docs-configuration-consistency.md).

The previous AWS account is closed. All production infrastructure controls above remain unverified deployment requirements; no active cloud deployment is asserted. The retained AWS workflow is manual-only, with explicit enablement and production-environment gates. See [Security Hardening V2](30-security-hardening-v2.md) for the current API, migration, concurrency and remaining-risk contract; historical cycle reports retain their original evidence.
