# Financial correctness: first engineering cycle

Scope approved on 2026-10-22: financial calculations, synthetic regression data,
chat database lifecycle, deterministic reviewer validation and traceability.
The existing fraud-investigation workspace and case creation are preserved.
No database migration or production data rewrite is included.

## Financial rules (cash-flow-v1)

- Monetary inputs must fit the existing `Numeric(12,2)` column. Reject non-finite
  values, values exceeding ten integer digits and values requiring fractional cents.
  Application totals use Decimal. Float is used only for anomaly statistics.
- Positive amounts remain gross income; negative amounts remain gross spending.
  Net cash flow is gross income minus gross spending. Existing summary fields
  retain these meanings, including credits from refunds and internal transfers.
- Every aggregate is scoped to one currency. A request with no currency may infer
  the sole currency in its relevant scope. Mixed currencies require explicit
  selection (HTTP 422 in the API). No exchange-rate conversion is performed.
  Empty scopes retain the historical USD default unless a currency is specified.
- Currency inputs are normalized to uppercase three-letter ASCII codes. This
  validates the format, not membership in a maintained ISO currency catalogue.
  CSV imports preserve `currency`/`Currency`; omission retains the USD default.
- The separate spending breakdown excludes exactly category `Internal Transfer`.
  It subtracts positive transactions explicitly categorized `Refund:<category>`
  from that category's spending. For example, `Refund:Groceries` reduces Groceries.
  Empty refund targets use Uncategorized. No merchant-name or sign-only inference
  classifies a refund or transfer. Refunds are recognized on their posting date;
  an unmatched refund can make net spending negative.
- Suspected duplicates share posting date, merchant, description, amount, currency
  and category within the user and reporting scope. Flag every member; retain all
  in calculations. No automatic deletion, exclusion or historical reclassification.
- Months use inclusive calendar-month start and exclusive next-month start.
  Comparisons mean second month minus first month. Gross spending deltas and
  refund-adjusted spending deltas are separate measures. Category contributions
  reconcile to the latter, not necessarily to gross spending changes.

## API and compatibility

Existing `GET /api/transactions/summary/{month}` accepts optional `?currency=EUR`.
Its monetary fields remain unchanged; `currency` is additive response metadata.

New `GET /api/transactions/spending/{month}?currency=EUR` returns gross cash flow,
net spending, category amounts, explicit refunds, transfer IDs, suspected duplicate
IDs and deterministic evidence. Add `&compare_to=2025-01` to compare that earlier
month to the path month. All queries use the authenticated user's ID.

Chat accepts optional `currency` without changing required request fields. Explicit
`YYYY-MM` periods in the message select a month; two distinct periods select a
comparison in their written order. Summary and category requests without a period
use the current UTC calendar month. Merchant, anomaly, recurring and budget tools
continue to label their existing scope as all history. Natural-language dates such
as named months and “last month” are not yet parsed; use explicit ISO periods.

Financial tool results add `_evidence` with a rule version, currency, period, facts,
source transaction IDs and per-fact supporting transaction IDs. Comparison facts
also separate the left and right supporting IDs. No RAG pipeline is added.
Supporting IDs are response evidence, not a separately persisted financial snapshot.

## AI trust boundary

Financial computations originate in application functions. The model can return
only `claim_ids` from trusted facts; it cannot supply monetary values, currencies,
periods, additional prose or transaction references. The reviewer verifies those
references, monetary precision, evidence context and membership in the authorized
source transaction set. The backend renders the selected facts. Unknown, omitted,
duplicated or additional claims use a deterministic fallback; invalid evidence is
rejected. Review status `accepted` describes the final verified response, and its
review message explicitly records replacement of an unsupported draft.

Retrieved document text cannot introduce financial values into this rendering.
Free-form financial explanations are intentionally replaced by factual templates
in this cycle. This reduces narrative flexibility while enforcing the trust boundary.

## Database lifecycle

The chat route captures user identity and checks session ownership, then ends the
initial read transaction before query embedding. RAG retrieval and financial reads
materialize plain results; that read transaction ends before answer generation.
After provider calls finish, ownership is rechecked and the chat session, both
messages and audit event commit together. A provider failure creates no partial turn.
Only the chat workflow uses this boundary; upload ingestion is not refactored here.

Reads and final writes are separate transactions. The answer describes the data
observed during analysis, not a serializable snapshot spanning external calls.
Evidence IDs let callers inspect those observations, but later transaction edits
can change recomputed results. A persisted historical snapshot is future work.

## Synthetic data and verification

`backend/tests/fixtures/synthetic_finance.py` generates 10 users, all 12 months of
2025 and exactly 3,000 EUR transactions using seed 20251022 and deterministic UUIDs.
It includes salary, rent, utilities, subscriptions, groceries, restaurants,
transport, positive refunds, paired internal transfers, duplicate observations
and an August spending spike. All identities use synthetic labels and example.invalid.
Expected results are computed independently in integer cents while constructing
the dataset, rather than by invoking the production analytics functions.

Export JSON from `backend` with:

```powershell
..\.venv\Scripts\python.exe -m tests.fixtures.synthetic_finance
```

The generator does not connect to or seed a database. Tests insert the fixture only
into isolated in-memory SQLite databases and check all 120 user/month combinations,
all category totals, treatment rules, user isolation and comparison reconciliation.

Additional tests cover currency mixing, precision boundaries, both CSV parsers,
unsupported reviewer drafts, reporting context, provider transaction boundaries,
provider failures and chat session ownership.

## Remaining limitations

- PostgreSQL and Redis integration checks require separately configured services.
- Historical transactions have no explicit refund/transfer relation or bank ID;
  categories are a documented convention, not proof of account ownership or refund linkage.
- Existing budget estimation retains all-history gross spending divided by three,
  now explicitly labelled. Recurring-payment cadence remains heuristic and is
  labelled unverified in explanations. Neither is suitable as a guaranteed forecast.
- Evidence reports materialize the relevant rows; very large ledgers need a later
  pagination or snapshot design that preserves complete calculations.
- Frontend rendering of evidence links and currency-selection controls is future
  work; this cycle exposes the backend evidence and keeps frontend types compatible.

## Changed files

- Backend schemas: `app/schemas/finance.py`, `app/schemas/chat.py`.
- Queries and analytics: `app/repositories/transactions.py`, `app/services/analytics.py`,
  new `app/services/financial_evidence.py` and `app/services/financial_review.py`.
- Ingestion: `app/services/ingestion.py`, `app/services/document_ingestion.py`.
- Chat and tools: `app/api/routes/chat.py`, `app/api/routes/transactions.py`,
  `app/agents/tools.py`, `app/agents/state.py`, `app/agents/orchestrator.py`, `app/services/llm.py`.
- Tests: financial correctness, financial review, synthetic finance, chat lifecycle,
  fixture generator and updated analytics/orchestration fakes.
- Frontend: additive optional summary currency type in `src/lib/api.ts`.

Validation evidence is recorded in [17-financial-cycle-validation.md](17-financial-cycle-validation.md).
