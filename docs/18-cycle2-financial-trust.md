# Cycle 2 — Financial Trust & Reliability

Approved scope: the five findings from the Cycle 1 review, plus explicit provider
identity, actionable validation errors, ownership-safe cleanup and staged TDD commits.
Baseline: `2f68d4a`. No migrations, application dependencies, pushes or deployments.

## Corrected findings

### 1. Imported labels remain data

Financial assertion wording comes from fixed backend templates selected by claim
type, not the fact's free-form label. Imported merchant/category names are rendered
separately as `Imported ... (untrusted data): "..."`. JSON escaping preserves the
original value while preventing newlines, control characters, quotes and Unicode
directional characters from changing the narrative layout. Both accepted model
drafts and deterministic fallback use this renderer.

Original transaction names are not rewritten. Grouping tools retain flat response
entries for compatibility, and `_evidence.group_totals` retains every group name,
including a literal `_evidence` name that would otherwise collide with metadata.

### 2. Currency and reporting context are enforced

Reporting supports AUD, CAD, CHF, EUR, GBP, JPY and USD. An unsupported reporting
currency now returns HTTP 422, even if historical records use that currency. Storage
continues accepting the existing three-letter format; no historical values change.
There is no currency conversion. This reporting restriction is an intentional,
documented behavior change; extending the supported set requires an explicit policy.

Structured chat currency, recognized text codes and explicit currency markers must
agree. Unknown or conflicting selections fail before retrieval/provider calls.
Ambiguous dollar notation is rejected with instructions to use a currency code.
The parser is a constrained English/ISO recognizer, not a general natural-language
date/currency interpreter; unfamiliar phrasing may require an explicit ISO request.

| Intent | Supported scope | No-period default |
|---|---|---|
| Summary/category | One YYYY-MM or comparison of two distinct YYYY-MM months | Current UTC calendar month |
| Merchant/anomaly | One YYYY-MM or all history | All history |
| Budget/recurring | All history only | All history |

Explicit unsupported scopes return HTTP 422. Relative periods, named months,
daily dates, quarters and inclusive date ranges are rejected instead of silently
defaulting to another scope. Two-month comparison direction remains second minus
first. Budget and recurring rules remain unchanged rather than being repurposed
for month-specific forecasts. Reviewer context checks apply to every financial intent.

### 3. CSV non-finite money is rejected early

Both ingestion paths check Decimal.is_finite() immediately after parsing and before
categorization/comparisons. NaN, sNaN, signed NaNs and positive/negative Infinity
return controlled HTTP 400 errors with the input line number, with or without a
provided category. Existing monetary scale/range checks remain in place.

### 4. Upload preparation precedes persistence

The authenticated user ID is captured before ending the authentication read
transaction. Staging, extraction, embedding generation/retries and S3 publication
run without an open request database transaction. The completed upload record,
transactions/cases or embeddings, and audit entries are then persisted atomically.
No upload completion is persisted while an embedding provider is still running.

Documents with no indexable text return HTTP 400. No new status was introduced:
the existing database constraint permits only uploaded/stored/processed/indexed/failed.
Success continues returning the existing file_id/status/imported/indexed fields.

EMBEDDING_BACKEND=openai is the default. Configured remote failures, an open circuit,
missing remote credentials/client or malformed provider output never activate local
embeddings. Uploads return actionable HTTP 503 responses for those embedding failures.
SDK-configured retries occur before persistence; blocked circuit calls do not reset
the cooldown. Response model, dimensions, finite coordinates, count and input indices
are validated by one policy shared with retrieval.

EMBEDDING_BACKEND=local explicitly selects a deterministic hash encoder. It is a
development/test encoder, not a semantic-model substitute. Indexing and querying
use the same encoder and model identity, deterministic-local-hash-v2. Retrieval
filters both model and dimensions. Existing local-v1 data is not automatically
rewritten or queried with v2; it requires deliberate re-ingestion/re-indexing.
This embedding setting does not remove the application's existing LLM credential
configuration requirements.

#### Cleanup and cross-system atomicity

- Staging files are exclusively created. A file already at the generated path is
  neither appended to nor registered as owned by the request.
- Cleanup only considers paths registered by that service/request. Foreign upload
  paths supplied to cleanup are ignored.
- S3 publication uses conditional creation (IfNoneMatch=*), preventing overwrite.
  Successful receipts register the exact created key, ETag and version when present.
  Rollback cleanup uses the matching ETag/version and never scans/deletes a prefix.
- A known failure before commit rolls back database work and cleans owned artifacts.
  Cleanup failures are logged as generic events without financial content or names.
- A failed/uncertain database commit acknowledgement does not prove rollback. Final
  storage is retained for reconciliation, protecting a potentially committed row.
- An interrupted/uncertain S3 acknowledgement can leave a new untracked object.
  Without a confirmed creation receipt it is deliberately not deleted. Successful
  uploads can also leave staging remnants if best-effort cleanup fails.

Filesystem, S3 and PostgreSQL are not one atomic transaction. Orphan reconciliation
remains manual; process termination/cancellation during blocking storage work may
also leave newly created artifacts. Reposting after a lost successful response is
not guaranteed exactly once and can create duplicates under the existing documented
duplicate policy. No cross-request idempotency protocol or cleanup worker was added.
Live S3 conditional requests and least-privilege cleanup permissions still need
deployment validation; mocked tests and installed SDK capability checks are not
proof of live storage behavior.

### 5. Evidence is reconciled against the calculation

Summary fields project the same computed fact values; comparison totals project
their corresponding delta facts rather than calculating another representation.
The validator checks Decimal precision, context, unique supported reference sets,
fact/aggregate equality, cash-flow arithmetic, category reconciliation, grouping
projections, comparison arithmetic and the exact left/right reference sets.

FinanceToolLayer captures the canonical serialized calculation before generation.
ReviewerAgent compares the later mutable projection against that request-local
snapshot. Internally consistent tampering with amounts, identifiers or metadata
therefore cannot replace the original tool result. This snapshot is detached,
request-local and not exposed as a client-supplied authority. Validation performs
no database reads and does not recalculate financial business rules independently.

Invalid model drafts with valid evidence use deterministic fallback. Inconsistent
evidence is rejected instead of being presented as a successful fallback. The
snapshot and references are not a persisted historical audit snapshot, and they
cannot compensate for a bug in the underlying calculator; independent oracle
tests remain necessary.

## Modified files

- Context/orchestration: `backend/app/services/financial_context.py` (new),
  `backend/app/agents/orchestrator.py`, `state.py`, `tools.py`,
  `backend/app/repositories/transactions.py`.
- Evidence: `backend/app/services/financial_evidence.py`, `financial_review.py`,
  `financial_validation.py` (new).
- Ingestion/provider lifecycle: `backend/app/services/ingestion.py`,
  `document_ingestion.py`, `rag.py`, `backend/app/api/routes/uploads.py`,
  `backend/app/core/config.py`, `openai_resilience.py`, `.env.example`.
- New regressions: `backend/tests/test_cycle2_labels.py`, `test_cycle2_context.py`,
  `test_cycle2_csv.py`, `test_cycle2_uploads.py`, `test_cycle2_evidence.py`.
- Updated fakes/configuration: `backend/tests/test_orchestrator.py`,
  `backend/tests/test_document_ingestion.py`.
- Documentation: this report, Cycle 2 validation and the delivery index.

## Logical implementation checkpoints

| Finding | Main implementation commits | Follow-up checkpoints |
|---|---|---|
| Label safety | 032933f | 7656338 preserves reserved names |
| Request context | 630e80e | 5e48b7a refines strict grammar; 370396b handles abbreviated months |
| CSV validation | 8f5a92f | Existing schema limits preserved |
| Upload lifecycle | b7ff02b | 1b6de64 cooldown/identity; 9cb325c shared retrieval validation; ca77376 schema compatibility |
| Evidence consistency | 9778d84 | 7656338 grouping reconciliation |

Each defect stage has a preceding executed failing-test checkpoint. See
[Cycle 2 validation](19-cycle2-validation.md) for RED/GREEN evidence and final results.

## Deferred work and release gates

No migration, application dependency, frontend redesign, worker, automatic deletion
job, historical reclassification or production permission change was introduced.
No code was pushed or deployed. Optional new architecture was deliberately deferred.

Before production release: PostgreSQL/Redis integration, production build and browser
end-to-end testing are mandatory. Also verify real async PostgreSQL upload failure
behavior, S3 conditional request/IAM support, model compatibility and operational
orphan-reconciliation procedures. Rollback must preserve storage and account for
older retrieval code lacking the new embedding-model filter. No automatic data
rollback/re-indexing is performed by these commits.

All-history analytics still materialize the selected ledger, and request-local
canonical serialization adds memory proportional to report size. Large-ledger
load testing, persisted historical evidence and currency-specific minor-unit scales
remain outside this cycle. Existing database monetary precision and financial
business rules are unchanged.
