# Document Q&A grounding and citation contract

## Confirmed defects

The original document-Q&A path treated the presence of retrieved chunks as proof
that a generated answer was grounded. It returned every retrieved chunk as a
citation without asking the model for references or validating references in its
answer. The model service also concatenated excerpts when the provider was
missing or failed, returning that preview through the same success-shaped
string contract.

The request threshold could be lowered below the default, and RAG retrieval did
not apply the threshold before its result limit. The document service passed an
unscoped query when the user owned no uploaded documents, which could include
other embedding source types for that user. Citation identity was derived from
JSON metadata rather than the embedding row's document and chunk columns.
When duplicate embedding rows shared a document/chunk reference, the model
could receive one row's text while the citation excerpt came from another.
Finally, the assistant UI offered finance chat only; there was no document
selection or document-Q&A interaction.

## Implemented corrections

- Document Q&A searches only uploaded-file chunks for documents selected from
  the authenticated user's ownership query. Unscoped requests resolve to that
  user's uploaded documents; an empty scope is rejected.
- Retrieval results carry source type, document ID, chunk index and embedding
  row ID from database columns. Citations are built from those fields, not
  mutable metadata.
- A server-generated `doc:<document-id>:chunk:<index>` reference is attached to
  each unique retrieved chunk. The model returns a JSON object containing an
  answer, references and an abstention flag. The service validates references
  against the retrieved set, rejects unknown references, deduplicates
  references using the same first matching chunk for model context and citation
  excerpt, and abstains if references are missing or invalid.
- Responses separate `citations` (valid references selected by the answer)
  from `sources` (all relevant authorized chunks retrieved). Excerpts are
  rendered as text, with no fabricated page numbers or source links.
- Grounding is always `false`: no claim-level semantic verifier exists.
  `grounding_note` states the limitation in both document-Q&A response paths.
- Provider failures return a typed, safe response rather than an extractive
  answer. Embedding-provider failures are distinguished from insufficient
  evidence. Database transactions are ended before embedding and synthesis
  provider calls.
- The mandatory relevance floor is server-controlled. Client values below
  `0.05` are clamped to that floor. Generic finance RAG calls that omit a
  threshold retain their previous no-threshold behavior.
- PostgreSQL applies relevance filtering before ordering/limit. The SQLite
  fallback streams database rows and keeps a deterministic, bounded top-k
  result set.
- Added an authenticated `GET /api/uploads` endpoint that returns only a user's
  file ID, filename, status and creation time. It does not expose storage paths
  or content. It pages at most 100 records per request. The UI loads pages and
  permits selecting up to 100 indexed documents.
- Unscoped document Q&A loads at most 101 owned document records and returns a
  clear `400` when the account has more than 100, requiring an explicit
  bounded scope instead of building an unbounded SQL `IN` list.

## Response status contract

| Status | Meaning | `grounded` | `abstained` | Used citations |
|---|---|---:|---:|---|
| `ok` | A non-empty model response parsed and every returned reference maps to a retrieved authorized chunk. | `false` | `false` | One or more validated references |
| `abstained` | The model abstained, or the response lacked a valid reference set. | `false` | `true` | Empty |
| `insufficient_evidence` | No chunks passed the relevance gate, or no indexed chunks were found. | `false` | `true` | Empty |
| `provider_error` | Embedding/model configuration, circuit, timeout/API call, empty output, or structured response validation failed. | `false` | `true` | Empty |
| `extractive_preview` | Reserved response shape for an explicitly labeled preview; current code does not emit this status or use an extractive fallback. | `false` | `true` | Empty |

Non-`ok` responses may include `sources` when retrieval succeeded before a
later model-provider failure or abstention. The answer's citation list remains
empty in those cases. Response validators reject contradictory status/boolean
and citation combinations. Document-mode chat uses the same typed citation,
source and status fields as the dedicated endpoint. Normal financial chat
continues to use its existing orchestration and persistence path.

## Citation guarantees and limitations

Every returned citation is selected from server-created references for
retrieved chunks whose database `user_id`, `source_type` and `source_id` satisfy
the authorized uploaded-document scope. Document names and chunk indices come
from the owned document record and embedding row. Duplicate references are
deduplicated; missing, invented or out-of-scope references cause abstention.
Page values remain `null`, because ingestion does not preserve page mapping.

A valid reference proves only that the chunk exists in the authorized retrieval
set. It does **not** prove that the chunk entails the cited sentence, nor that
every factual claim in an answer is supported. Thus, an `ok` response is
reference-validated, not semantically verified, and `grounded` remains false.
No second model is used as a verifier.

## Relevance score semantics and threshold

Both retrieval implementations use cosine similarity: SQLite computes cosine
similarity directly; PostgreSQL pgvector's `<=>` operator returns cosine
distance, converted to similarity with `1 - distance`. Higher values are more
relevant; cosine similarity is mathematically bounded to `[-1, 1]`. Chunks with
missing scores fail the document-Q&A relevance gate.

The mandatory default floor is `0.05`; clients cannot lower it, though they may
request a stricter value up to `1.0`. This is a conservative operational floor,
not an empirically calibrated relevance boundary. The local hash embedding and
provider embeddings may have different retrieval quality; the threshold has
not been calibrated against production documents.

## Provider failures and resource bounds

Missing model configuration, an open circuit, provider timeout/API errors,
empty responses, malformed structured JSON and invalid response shapes produce
`provider_error`. Embedding-provider failures also produce `provider_error`,
not an evidence-insufficiency response. Provider details and credentials are
not returned. There is no concatenated-excerpt fallback. Provider timeout and
retry bounds come from the existing OpenAI settings; synthesis is capped at
450 output tokens, retrieval at 20 chunks, and questions at 4,000 characters.

## Authorization and endpoints

Document ownership is checked with a database query constrained by the
authenticated `user_id`. Requested missing, foreign, or mixed-scope IDs all
return the same `404 Document not found` response. Retrieval is additionally
constrained by `Embedding.user_id`, `source_type='upload'`, and authorized
document IDs. Citation metadata is never trusted to decide ownership.

`POST /api/documents/ask` is the canonical dedicated endpoint. The existing
`/api/documents/qa`, `/api/documents/question-answer`, `/api/document-qa` and
`/api/document-question-answer` aliases remain for compatibility. Existing
`POST /api/chat` supports `mode: "document_qa"`; its default finance mode and
its existing callers are preserved. Contradictory `question`/`message` or
`document_ids`/`document_scope` values are rejected.

The authenticated document picker uses paginated `GET /api/uploads` and only
submits selected indexed document IDs (up to 100). Unscoped document mode is
restricted to the authenticated user and rejects accounts with more than 100
documents so callers can provide an explicit selection. The existing assistant
also retains its finance mode. Citation and retrieved-source excerpts render
as plain text; the UI distinguishes cited references, retrieved sources,
abstention and provider failure.

## Validation results

Results recorded for the hardening branch:

- Backend: `python -m ruff check app tests evaluation` — passed.
- Backend formatting: `python -m ruff format --check` on all changed Python
  files — passed.
- Focused backend QA, RAG, pgvector integration and financial chat tests:
  **37 passed**.
- Backend full suite: `python -m pytest -q -rs` with disposable
  PostgreSQL/pgvector and Redis test URLs — **590 passed, 0 skipped**. The four
  Redis-dependent tests were exercised against a local-only disposable Redis
  container; without `TEST_REDIS_URL`, those tests report explicit skips.
- PostgreSQL/pgvector: isolated schema creation, actual indexing, threshold
  score ordering, mixed-owner document scope and unscoped owner isolation —
  **2 integration tests passed** (including the existing upload/index/chat
  integration). The database ran in a unique local-only disposable container.
- Frontend: `npm.cmd run lint`, `npm.cmd run typecheck`, and
  `npm.cmd run build` — passed.
- Playwright: targeted Chromium document-Q&A flows — **3 passed**, covering
  authenticated document listing and chat requests, indexed document
  selection, citation rendering as text, abstention and provider-error states.
  Command: `npm.cmd run test:e2e -- --project=chromium
  tests/e2e/assistant/document-qa.spec.ts`.
  The repository's test server prints a warning because `next start` is used
  with standalone output; the targeted tests still completed successfully.
- Deterministic AI/RAG evaluation (`python -m evaluation.runner`):
  **18 cases; 15 passed, 0 failed, 3 partial**. The partial cases explicitly
  represent the evaluator's
  unsupported document-Q&A answer-quality capability. Its
  `document_citation_correctness` and semantic-faithfulness metrics remain
  unevaluated.

## Known limitations and deferred improvements

- Claim-level entailment, completeness and contradiction checking are not
  implemented; no financial accuracy or production-readiness claim is made.
- The `0.05` relevance floor has no empirical calibration and should be
  evaluated against representative, consented document/query judgments before
  tuning.
- Ingestion does not retain page offsets, so citations identify chunks, not
  pages.
- SQLite computes exact scores in process and scans the user's matching
  embeddings; the maintained result set is bounded, but retrieval cost still
  grows with the indexed corpus. PostgreSQL uses pgvector ordering/filtering.
- The document selector is paginated, but the client can load every page and
  selected document names are bounded per Q&A request rather than implementing
  search over very large document libraries.
- The existing evaluation harness does not score document answer quality,
  citation entailment or abstention accuracy. New deterministic regression
  tests cover reference validity, abstention, source isolation, score
  boundaries and provider behavior, but they are not a semantic benchmark.
- The `extractive_preview` status is reserved for a future, explicitly
  requested preview mode and is not emitted by this implementation.
