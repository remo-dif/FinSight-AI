# Cycle 2 validation — 2026-10-22

Scope and modified files: [18-cycle2-financial-trust.md](18-cycle2-financial-trust.md).
Baseline commit: `2f68d4a`. Final tested code commit: `370396b`.
Documentation-only changes follow that code checkpoint.

ECC change-impact, tdd-workflow and verification-loop guided the approved work.
Each confirmed fix had executed failing regression evidence before production edits.
No files from earlier user work were discarded; the baseline working tree was clean.

## Final executed checks

| Check | Result |
|---|---|
| Complete backend pytest suite | **196 passed, 0 failed, 2 skipped** |
| Backend application statement coverage | **84.76%**; 2,448 statements, 373 missed |
| Coverage gate | Passed, minimum 80% |
| Backend Ruff check, all app/tests | Passed |
| Financial renderer statement coverage | 100.00% |
| Financial consistency validator | 80.34% |
| Financial evidence builder | 98.18% |
| Financial context resolver | 90.48% |
| Upload route | 100.00% |
| Document ingestion | 83.91% |
| Financial tools | 97.10% |
| Existing transaction repository | 97.37% |
| Existing financial analytics | 95.16% |

The final suite completed in 13.94 seconds. The existing case repository emitted
21 SQLAlchemy Result.tuples() deprecation warnings. No unresolved test failures.
Coverage is statement coverage; these percentages are not branch, concurrency or
production-integration guarantees.

Commands actually executed from `backend`, with synthetic test configuration:

```powershell
..\.venv\Scripts\python.exe -m coverage run --source=app -m pytest -q -p no:cacheprovider -o faulthandler_timeout=30 --tb=short
..\.venv\Scripts\python.exe -m coverage report --precision=2 --fail-under=80
..\.venv\Scripts\python.exe -m ruff check app tests --no-cache
```

DATABASE_URL was in-memory SQLite. JWT settings and the OpenAI key were explicit
synthetic placeholders. PYTHONDONTWRITEBYTECODE was enabled. Real providers and S3
operations were mocked in regressions; no production credentials or data were used.
The existing environment already supplied pytest, Ruff and coverage. No application
dependency declarations were changed and no new application dependency was installed.

## Regression targets and executed RED/GREEN evidence

Each targeted run used `python -m pytest <target> -q -p no:cacheprovider`, with
short/line traceback variants. GREEN counts below sometimes include the same
target plus its adjacent existing regressions; they do not represent independent
new tests being invented after a failure.

| Defect / target | Executed RED | Verified GREEN / checkpoint |
|---|---|---|
| Imported names: test_cycle2_labels.py | 14 failed (`778d12a`) | 35 passed including reviewer/routing tests (`032933f`) |
| Request context: test_cycle2_context.py | 17 failed (`338c18b`) | 48 passed with financial/chat targets (`630e80e`) |
| CSV validation: test_cycle2_csv.py | 12 failed, 12 passed (`b7cd5c5`) | 49 passed with ingestion/financial targets (`8f5a92f`) |
| Upload/provider/cleanup: test_cycle2_uploads.py | 12 failed (`ec80bd6`) | 27 passed with ingestion/chat/RAG targets, then full suite 161 passed / 2 skipped (`b7ff02b`) |
| Local identity and owned S3 cleanup | 1 failed, 14 passed (`0a86fe4`) | Legacy model excluded; included in the full-suite GREEN above |
| Evidence consistency: test_cycle2_evidence.py | 10 failed, 1 passed (`8d4c3e0`) | 75 passed with financial/reviewer targets (`9778d84`) |
| Context grammar / ordinary words | 7 failed, 17 passed (`5d24c14`) | 35 passed with chat/routing targets (`5e48b7a`) |
| Circuit cooldown and remote model identity | 2 failed, 22 passed (`5166464`) | 29 passed with ingestion target (`1b6de64`) |
| Retrieval with wrong remote model | 1 failed, 24 passed (`1e1b089`) | 31 passed with ingestion/RAG targets (`9cb325c`) |
| Reserved imported metadata name | 3 failed, 14 passed (`5de3fbd`) | 48 passed with evidence/financial targets (`7656338`) |
| Textless upload / existing status constraint | 1 failed, 25 passed (`1e8b95c`) | 26 upload tests passed (`ca77376`) |
| Abbreviated periods | 3 failed, 24 passed (`7b59880`) | 27 context tests passed (`370396b`) |

Final complete GREEN includes every target: **196 passed, 2 skipped**. These local
checkpoint commits preserve evidence; no commits were pushed or history rewritten.

## What the tests prove

- Category and merchant names containing injected monetary assertions, CR/LF,
  control bytes, quotes and directional Unicode remain explicitly escaped data.
  The same guarantee applies to deterministic fallback and reserved `_evidence` names.
- Unsupported/conflicting currency and period requests produce actionable HTTP 422
  before provider calls. Monthly merchant selection filters the actual ledger.
  Reviewer checks all relevant intents against their resolved period.
- Both CSV implementations reject all tested non-finite forms with HTTP 400 before
  invoking categorization, regardless of whether a category was supplied.
- Upload extraction, embedding and S3 publication run without a request transaction.
  Provider/pre-commit persistence failures leave no completed upload/embedding rows.
  Upload tests use real SQLite transactions behind an async-session adapter;
  real asynchronous PostgreSQL/connection-pool behavior remains an integration gate.
- Local mode is explicit. Missing/failed remote providers, unexpected remote models,
  incomplete/wrong-dimensional/non-finite vectors and an open circuit never trigger
  local substitution. Valid provider indices are restored to input order.
- Retrieval skips mismatched model/dimension records, and rejects an unexpected
  remote query model before database access. Local-v1 records are excluded from v2.
- Ownership-safe cleanup preserves staging collisions, foreign files and pre-existing
  mocked S3 objects. Conditional receipt-based cleanup occurs only for owned objects.
  Combined provider, S3 acknowledgement, flush, commit and cleanup failures exercise
  the documented conservative orphan-retention rules.
- Altered totals/facts, missing category facts, cash-flow inconsistencies, duplicate
  references, comparison deltas and incorrect left/right reference sets are rejected.
  An internally consistent altered report is also rejected against the captured
  canonical result, without querying the database during review.
- Existing gross cash flow, refunds, internal transfers, duplicate retention, case
  creation, authentication/user-scoped access and the independent 3,000-row EUR
  synthetic oracle continue passing their existing tests.

The installed botocore service model was checked locally: PutObject supports
IfNoneMatch and DeleteObject supports IfMatch. This was an SDK-capability inspection,
not an executed live S3 operation.

## Skipped and unexecuted release checks

- PostgreSQL migration smoke integration skipped: TEST_DATABASE_URL not configured.
  No database migration was executed, added or edited.
- Redis integration skipped: TEST_REDIS_URL not configured.
- Production build and browser end-to-end tests were **not executed** in Cycle 2.
- Live OpenAI/S3/IAM and real async PostgreSQL failure tests were **not executed**.
- Frontend files were unchanged; frontend checks were not rerun in Cycle 2.
- A separate Python static type checker and dependency/security scanner were not run.
  Ruff and the full backend tests passed; those are not substitutes for those checks.

## Remaining risks / deliberately deferred changes

Storage and database persistence cannot provide cross-system atomicity. Uncertain
commit/storage acknowledgements or process termination may leave new orphaned
artifacts. Exactly-once cross-request retry, automated orphan cleanup, durable
historical evidence and legacy-local re-indexing require separate work. Existing
user files are never enumerated or automatically removed to resolve those cases.

The strict context grammar is documented rather than presented as complete natural
language understanding. Supported reporting currencies are explicitly limited;
historical unsupported-currency data is retained, not converted/reclassified.
The in-process canonical snapshot verifies projection integrity, not independent
correctness of every calculator or authenticity of imported bank data.

No new schema, application dependency, background worker, automatic data rewrite,
production permission change, unrelated UI change, push or deployment was made.
Release remains blocked on PostgreSQL/Redis integration, production build and
browser E2E validation, with live storage/IAM and model compatibility checks also
required before deploying this upload workflow. No production-readiness claim.
