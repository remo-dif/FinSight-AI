# 14. Security Layer

## Controls Implemented

- JWT access token issuing and validation.
- bcrypt password hashing.
- Role-based dependency checks.
- Secure upload validation for extension, MIME type, size, and path isolation.
- Audit logging model for auth, upload, and AI tool actions.
- Rate limiting middleware.
- CORS restricted by environment variable.

## Threat Model

- Malicious upload: reject unsupported type, cap size, isolate storage path, parse through controlled services.
- Prompt injection in documents: retrieved text is treated as untrusted context and reviewed before response.
- Data exfiltration through chat: LLM has no SQL access and can call only approved tools.
- Token compromise: short-lived access tokens, refresh-token roadmap, secure secret management.

## Production Hardening

- Persist refresh token hashes with rotation.
- Add object storage malware scanning.
- Add KMS-backed encryption for sensitive extracted text.
- Move rate limits to Redis.
- Add SIEM export for audit logs.
