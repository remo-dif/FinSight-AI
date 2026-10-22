# Financial cycle validation — 2026-10-22

Source: the user-approved five-task engineering cycle and financial rules recorded
in [16-financial-correctness-cycle.md](16-financial-correctness-cycle.md).
ECC change-impact, tdd-workflow and verification-loop guided this work.

## Executed results

| Check | Result |
|---|---|
| Complete backend pytest suite | 91 passed, 0 failed, 2 skipped |
| Application statement coverage | 80.54% (2,133 statements, 415 missed); 80% gate passed |
| Transaction repository coverage | 97.33% |
| Financial evidence coverage | 98.08% |
| Financial reviewer coverage | 100.00% |
| Financial tools coverage | 100.00% |
| Analytics coverage | 95.16% |
| Backend Ruff lint | Passed |
| Frontend TypeScript | Passed |
| Frontend ESLint | Passed |

Backend commands, run from `backend`:

```powershell
..\.venv\Scripts\python.exe -m coverage run --source=app -m pytest -q -p no:cacheprovider
..\.venv\Scripts\python.exe -m coverage report --precision=2 --fail-under=80
..\.venv\Scripts\python.exe -m ruff check app tests --no-cache
```

Test settings used an in-memory SQLite DATABASE_URL and explicit synthetic JWT
and OpenAI placeholders. Provider behavior was mocked in the financial LLM and
chat lifecycle tests. No real credentials or production database were needed.
The full suite required execution outside the Windows filesystem sandbox because
the existing HTTP/thread and temporary-file tests stalled inside it.

Frontend commands, run from `frontend`:

```powershell
npm.cmd run typecheck
npm.cmd run lint
```

The existing editable backend package built successfully during restoration of
declared development dependencies. Missing `greenlet` was installed through the
already-declared SQLAlchemy asyncio extra. Coverage was installed as a local
test measurement tool; application dependency declarations were not expanded.

## Guarantees exercised

| Guarantee | Test source |
|---|---|
| Reject fractional cents, overflow, NaN and Infinity; normalize currency | test_financial_correctness.py |
| Both CSV parsers retain EUR and return HTTP 400 for invalid precision | test_financial_correctness.py |
| Gross cash-flow semantics remain; separate net spending subtracts explicit refunds and excludes transfers | test_financial_correctness.py |
| Mixed currencies require selection, including cross-month comparisons | test_financial_correctness.py, test_financial_api.py |
| EUR 240 increase reconciles to EUR 110 groceries plus EUR 130 subscriptions with supporting IDs | test_financial_correctness.py |
| Existing summary, merchant, category and budget calculations remain available | test_financial_correctness.py, test_analytics.py |
| Deterministic schema-compatible 3,000-row ledger and independent cent oracle match all 120 user/month totals and categories | test_synthetic_finance.py |
| Duplicate observations remain counted and flagged; paired transfers and refunds follow documented rules | test_synthetic_finance.py |
| Evidence never references another user's transactions; HTTP aggregates remain user-scoped | test_synthetic_finance.py, test_financial_api.py |
| Invalid monetary claims, currency, periods, extra prose, omitted facts and unauthorized transaction references cannot reach the answer | test_financial_review.py |
| Retrieved document text cannot inject financial values; provider failures return trusted claim IDs | test_financial_llm.py |
| Embedding and LLM calls execute with no open database transaction | test_chat_lifecycle.py |
| Provider or persistence failures leave no partial chat session/messages | test_chat_lifecycle.py |
| Foreign chat sessions are rejected before provider calls; existing sessions still accept complete turns | test_chat_lifecycle.py |
| Current LangGraph specialist routing and case workflows continue passing | test_orchestrator.py, test_cases.py |

## RED/GREEN evidence

Initial test execution was blocked during collection by missing `greenlet`; that
was an environment failure, not valid RED evidence. Dependencies were restored.

The first new precision target then executed: **3 failed, 2 passed**. Failures
confirmed acceptance of fractional cents, monetary overflow and lowercase currency.
Local checkpoint: `b704ea8`. After the schema fix those five tests passed;
implementation checkpoint: `a829370`.

The expanded correctness target executed: **5 failed, 5 passed**. Failures confirmed
currency mixing, missing traceable spending reports, loss of CSV currency in both
parsers and acceptance of an unsupported AI claim. Local checkpoint: `a2a0bca`.

The final complete target is **91 passed, 2 skipped** after implementation and
additional compatibility/failure-path tests. Scenarios beyond those two recorded
RED targets have final GREEN evidence; separate RED runs were not captured for
each additional scenario. Checkpoint evidence is local; nothing was pushed.

## Skips, warnings and unexecuted checks

- PostgreSQL migration smoke test skipped: TEST_DATABASE_URL is not configured.
  No migration was executed or added.
- Redis integration test skipped: TEST_REDIS_URL is not configured.
- The suite emitted 21 SQLAlchemy deprecation warnings in the existing case
  repository's Result.tuples() calls. They did not fail tests.
- Production frontend build, browser E2E, live OpenAI calls and deployment were
  not run. Python static type checking was not run; pytest/imports and Ruff were.
- Coverage is statement coverage, not branch coverage. Existing RAG and legacy
  free-form LLM paths remain less covered than the new deterministic financial path.

Recommended next checks: PostgreSQL/Redis integration against disposable services,
then frontend evidence-link and currency-selection controls as a separate product cycle.
