# RAG Evaluation V1 foundations

## Purpose and boundary

PR1 provides a versioned synthetic corpus and document-Q&A annotations. Passing the PR1 validation tests does not establish retrieval accuracy, groundedness or production AI quality.

The new loader performs no ingestion, retrieval, generation, answer grading or provider calls. It does not connect to a database. The application already exposes document Q&A. Semantic document-answer evaluation is not implemented in the legacy runner.

## Files and schema

- `backend/evaluation/schemas.py` defines strict Pydantic v2 structures and `load_document_dataset()`.
- `backend/evaluation/data/corpus/manifest.json` has schema version 1, corpus version 1.0.0, description and document entries.
- Each document has a logical key, fictional owner, relative UTF-8 text path, SHA-256 of exact file bytes and evidence passages with logical keys and exact text.
- `backend/evaluation/data/document_qa_v1.json` has schema version 2, dataset version 1.1.0, matching corpus version, description and cases.
- Each case names its question, category, answerability, principal, explicit document scope, relevant evidence, required/forbidden assertion annotations, semantic expected outcome, nullable literal API status, HTTP status and expected sources.
- Assertions contain text, review rationale and evidence references. Required assertions must reference relevant evidence. Forbidden assertions may have no supporting evidence because they describe unsupported claims.
- `backend/evaluation/data/corpus/.gitattributes` preserves LF endings in text documents, including on Windows checkouts, so byte hashes remain reproducible.

Logical document/evidence keys identify fixture concepts. Runtime database UUIDs and chunk indices are deliberately absent. A future isolated loader must map these keys to newly created runtime records under the specified synthetic owners. No annotations grant runtime access.

A document content revision is its exact SHA-256. Preserve logical keys while updating content, revision hash, corpus version and dependent annotations together. Evidence keys remain stable only while their meaning remains stable. Evidence text must appear exactly once in its named document. Repeated or missing anchors require an unambiguous new passage annotation.

## Corpus and cases

There are six entirely fictional documents and twelve evidence passages. The documents cover an EUR account statement, expense breakdown, recognized revenue and receipts, February budget proposals, an unrelated USD account and a second owner's private plan.

The January EUR arithmetic is 1000.00 opening + 600.00 receipts - 250.00 payments = 1350.00 closing. Office supplies 100.00 + utilities 150.00 = 250.00 expenses. Recognized revenue 800.00 less uncollected 200.00 = 600.00 receipts. EUR and USD accounts have separate identities, with no asserted exchange rate. The two February budget figures are intentionally unresolved competing proposals, not inconsistent actual transactions.

The fourteen cases cover factual answers, amounts/currencies, dates, terminology, multiple documents, distractors, missing actuals/exchange rates, ambiguity, conflicting proposals, unsupported assertions, foreign-only scope and mixed owned/foreign scope.

The annotations were checked against the synthetic text and deterministic financial reconciliation tests during implementation. A separate human semantic review has not been performed. Required/forbidden assertions are review annotations, not substring grading rules. Forbidden assertions are representative, not exhaustive. Q06 forbids both EUR 300.00 (plan) and EUR 350.00 (unresolved draft) as confirmed February actual expenses; the corpus provides no actual total. Future graders must consider negation, units, scope and unsupported additional claims.

## Integrity guarantees

The combined bundle rejects duplicate cases, documents, paths and per-document evidence identifiers; unknown scope/evidence/source references; empty questions; malformed revision hashes; hash mismatches; missing or ambiguous passage anchors; incompatible corpus versions; unknown fields; malformed assertions; contradictory statuses and overlapping identical required/forbidden assertions.

Ordinary cases can reference only documents in scope owned by their principal. An authorization-negative case must include a foreign document and use category `unauthorized_scope`, answerability `unauthorized`, expected outcome `authorization_denied` and HTTP 404. The literal expected API status is null because HTTP 404 does not return a document-Q&A response body. Such cases cannot expect returned sources or required answer assertions. All evidence references, including assertion evidence, must belong to the explicit document scope in every case. Authorization-negative annotations may identify foreign-owned passages only when their documents are requested in that scope; ownership rules remain separate.

Answerable cases require evidence, supported assertion references and expected sources matching the relevant documents. Other cases expect semantic abstention with HTTP 200 and no used citations. Relevant passages may still be annotated for conflicts. Expected sources mean used citations; future checks must distinguish them from the application's retrieved `sources` field.

Paths must resolve inside the local corpus directory and name text files. This loader is an offline developer utility reading repository-controlled files. It is not an API or a general sandbox for attacker-controlled corpora.

Schema validation cannot establish semantic truth, completeness of relevance labels, resistance to prompt injection, correct application authorization, retrieval rank, citation entailment or answer quality. It detects structural contradictions and exact assertion overlap, not logically contradictory paraphrases.


## Outcome and API status contract

Dataset schema version 2 replaces the former ambiguous `expected_status` with three separate fields. This is an intentional dataset-schema change; corpus schema/version and legacy datasets/reports are unchanged.

| Semantic `expected_outcome` | Literal `expected_api_status` | `expected_http_status` |
| --- | --- | --- |
| `answerable` | `ok` | 200 |
| `abstention_required` | null, or an explicitly justified `abstained` / `insufficient_evidence` | 200 |
| `authorization_denied` | null | 404 |

All current nonanswer cases use null because the exact API status depends on retrieval and synthesis. `DocumentQAService` returns `insufficient_evidence` when no usable chunks are found, and `abstained` when synthesis abstains or valid references cannot be established. Null means no exact literal-status assertion is specified; the semantic outcome remains required. A future evaluator must still classify provider failures separately, rather than count any status as successful abstention. Provider-error behavior is outside this dataset's semantic fixtures.

Q10 and Q11 continue to expect HTTP 404 for foreign-only and mixed requested scopes. There is no literal document-Q&A status `authorization_denied`. No response grader is implemented here.

## Validation and extension

From `backend/`, validate without providers or environment secrets:

```sh
python -B -c "from evaluation.schemas import load_document_dataset; b = load_document_dataset(); print(len(b.corpus.documents), len(b.dataset.cases))"
python -B -m pytest -q -p no:cacheprovider tests/test_rag_evaluation_schema.py
```

To add a case, first inspect the corpus, select a unique case ID and explicit principal/scope, annotate answerability and HTTP behavior, then select evidence passages and independently author expected/forbidden assertions. Add a new synthetic document only when needed. Update the exact-byte hash and version metadata for changed corpus content. Run integrity and legacy tests. Have another reviewer inspect numerical facts and semantic expectations before using the dataset to assess model quality.

No private customer documents, account secrets or provider credentials belong in this corpus or future reports. Future integrations must instantiate both synthetic owners in an isolated database and call the existing authorized services. Direct reads of all embeddings must never stand in for an authorization test.

## Legacy compatibility

The existing `python -m evaluation.runner` benchmark retains its 18 synthetic cases, SQLite environment, local-hash retrieval, mocked financial provider, metric definitions, classifications and versioned baseline. Only explanatory text/comments were clarified in PR1. The historical `document_qa_and_document_citations_not_implemented` capability-gap string is retained for machine-readable compatibility; it describes missing evaluation in that runner, not the application's available Q&A endpoints.

A regression test compares the entire freshly evaluated legacy report with `evaluation/baseline.json`. The new document dataset is not automatically evaluated by that runner. Passing legacy results does not measure production document-Q&A quality.

## Next increments

PR2 evaluates the fixed corpus through production upload and pgvector retrieval in an isolated test environment. See the retrieval evaluation section below.

PR3 exercises document answers, citation validity and abstention using controlled SDK outputs. See the answer evaluation section below.

PR4 compares compatible offline evaluation contracts against versioned baselines. See the regression baseline section below.

## Verification during implementation

Commands were executed from `backend/` using Python 3.12, installed Pydantic 2.13.4 and Ruff 0.17.3. No dependencies were installed. Test processes used explicit synthetic DATABASE_URL=sqlite://, JWT placeholders, a non-provider OPENAI_API_KEY placeholder and EMBEDDING_BACKEND=local. TEST_DATABASE_URL and TEST_REDIS_URL were unset for the full suite. Bytecode and pytest cache generation were disabled.

- Initial schema run, `python -B -m pytest -q -p no:cacheprovider tests/test_rag_evaluation_schema.py --tb=short`, passed 41 tests. Four additional integrity/compatibility tests were then added.
- Final focused run, `python -B -m pytest -q -p no:cacheprovider tests/test_rag_evaluation_schema.py tests/test_rag_evaluation.py tests/test_document_grounded_qa.py tests/test_rag.py tests/test_ai_observability.py tests/test_ai_rag_integration.py --tb=short`, passed 106 tests with 2 skipped and zero failures. The skipped tests require TEST_DATABASE_URL for real PostgreSQL/pgvector.
- Full backend run, `python -B -m pytest -q -p no:cacheprovider --tb=short`, passed 652 tests with 48 skipped and zero failures in 135.57 seconds. Service-backed PostgreSQL/Redis checks, including dependent real-cookie browser checks, were unavailable without isolated service URLs. These skips are not integration success evidence.
- `python -m ruff check .` passed. `python -m ruff format --check .` passed with 115 files formatted. The formatter was applied only to the two new Python files.
- `python -B -c "from evaluation.schemas import load_document_dataset; b = load_document_dataset(); print(len(b.corpus.documents), len(b.dataset.cases))"` loaded 6 documents and 14 cases successfully.
- The new full-report compatibility assertion passed against the unchanged legacy baseline.
- `git diff --check` passed. Git attributes reported text=set and eol=lf for the corpus documents.

No PostgreSQL/pgvector integration result is claimed from SQLite execution. Frontend checks, live model evaluation and hosted CI were not run for these backend-only dataset foundations.

Production retrieval, chunking, embeddings, document-Q&A behavior, LLM prompts, frontend, authentication, deployment workflows and safety gates are outside these changes. No dependencies or migrations are added. Work remains local and uncommitted.

## Independent review corrections

The three reviewed P2 findings were reproduced with new regression tests before changes. The RED command was `python -B -m pytest -q -p no:cacheprovider tests/test_rag_evaluation_schema.py -k 'outside_requested_scope or literal_status or q06' --tb=short`. It produced 3 failed, 45 deselected. Q10 accepted a known account-january passage outside its private-plan scope; the semantic/API split was missing; Q06 lacked the EUR 350.00 forbidden annotation.

Current correction verification results are recorded below. The earlier verification section records historical PR1 results.

Commands below were executed from `backend/` with the same synthetic/offline configuration described above. TEST_DATABASE_URL and TEST_REDIS_URL were unset.

- `python -B -m pytest -q -p no:cacheprovider tests/test_rag_evaluation_schema.py tests/test_rag_evaluation.py tests/test_document_grounded_qa.py tests/test_ai_rag_integration.py --tb=short -rs` produced 106 passed, 2 skipped, zero failures. Both skips require PostgreSQL/pgvector via TEST_DATABASE_URL.
- `python -B -m pytest -q -p no:cacheprovider --tb=short -rs` produced 665 passed, 48 skipped, zero failures in 53.24 seconds. Skips require isolated PostgreSQL/pgvector or Redis, including dependent authentication, real-cookie, concurrency and migration tests.
- Ruff 0.17.3, `python -m ruff check .` and `python -m ruff format --check .`, passed with 115 Python files formatted.
- `python -B -c "from evaluation.schemas import load_document_dataset; b=load_document_dataset(); print(len(b.dataset.cases), len(b.corpus.documents))"` confirmed 14 valid cases and six verified corpus hashes. Q06 retains semantic abstention; Q10/Q11 retain HTTP 404 and no literal Q&A status.
- The full legacy-report/baseline equality regression passed. Git diff confirms no changes to the legacy dataset, baseline, corpus, runner, production services, dependencies, authentication or deployment files.
- `git diff --check` passed. Only schemas.py, document_qa_v1.json, test_rag_evaluation_schema.py and this document changed.

The existing branch is named `feat/rag-evaluation-v1-foundations` (plural), based on commit 74fb4c6934a1bc1ce1e57caae2fb15de90ff93ec. Corrections remain uncommitted. No PR2 functionality, response grader, deployment or publishing operation was introduced.

## PR2 retrieval evaluation

Run from `backend/` with installed development dependencies and a disposable local PostgreSQL database using the existing pgvector/PG16 image. Use synthetic application settings and a dedicated test URL. The port below is an example for a container published on loopback.

```powershell
$env:DATABASE_URL = 'sqlite://'
$env:JWT_SECRET_KEY = 'retrieval-eval-access-placeholder-1234567890'
$env:JWT_REFRESH_SECRET_KEY = 'retrieval-eval-refresh-placeholder-1234567890'
$env:OPENAI_API_KEY = 'retrieval-eval-placeholder-no-provider'
$env:APP_ENV = 'development'
$env:TEST_DATABASE_URL = 'postgresql+psycopg://eval_user:eval_password@127.0.0.1:55432/finsight_retrieval_test'
python -B -m evaluation.retrieval_runner --k 5 --min-score 0.05
```

The SQLite value above only initializes unused default application settings. The runner requires `TEST_DATABASE_URL`, rejects non-loopback addresses and URL query overrides, and routes every ASGI database dependency to a fresh PostgreSQL schema. Use a dedicated disposable server because setup may install the `vector` extension in its database. Tables and test accounts live in the temporary schema, with upload storage in a temporary directory. The runner drops its schema and releases its storage on exit. Redis is unnecessary for this harness, which uses the in-memory rate limiter.

The CLI writes a versioned JSON report to stdout and returns a nonzero code on an incomplete run. It forces local embeddings and uses authenticated synthetic users. Fixed synthetic upload identities stabilize the production SQL tie breaker. Reported identifiers are logical document keys and chunk positions. Score, hash and span metadata are included without raw documents, queries, credentials or vectors. The manifest includes HEAD and whether the working tree is dirty. Keep a clean checkout when saving a reproducible baseline. The schema uses real pgvector operators, while the HNSW index created by migrations is absent from the metadata-created test schema.

### Evidence alignment

The deterministic PDF renderer uses explicit WinAnsi encoding and wraps text across lines and pages. The production extractor must reproduce the original text after whitespace normalization and preserve all annotated anchors. The real upload endpoint runs extraction, chunking, local embedding and persistence. Persisted text and SHA-256 must match the expected positions in the normalized document under the production chunk size and overlap. Missing, duplicated or misaligned positions fail the run. Anchors that become ambiguous or disappear after extraction also fail the run. Mapping uses half-open document-local token spans; the union of retrieved spans credits each covered token once. The long fixture tests overlap and split passages separately from the PR1 corpus.

### Metrics and tracks

For the first k ranked positions, let c(e) be the fraction of an annotated passage e covered by the union of retrieved spans in its document.

| Metric | Calculation |
| --- | --- |
| Evidence Recall@k | Number of passages with c(e) = 1 divided by number of annotated passages |
| Evidence Coverage@k | Mean c(e) across annotated passages |
| Chunk Precision@k | Number of returned positions with any positive evidence overlap divided by k |
| Novel Evidence Precision@k | Number of positions containing at least one complete passage not previously credited to a chunk divided by k |
| MRR@k | Reciprocal rank of first evidence contact, or zero if no chunk overlaps |

Duplicates can count for conventional precision. They add no novel credit for a passage already credited. Missing positions count against both precision denominators. A passage split across chunks can be fully covered by their union even if no chunk earns novel credit. MRR measures first contact, independent of full passage coverage.

Eight answerable cases feed the primary retrieval aggregate. Q08 has a separate conflict aggregate. Q06, Q07 and Q12 report counts and rankings with null relevance metrics; a retrieval result alone says nothing about answer abstention. Q10 and Q11 use the authenticated document-Q&A endpoint. They require HTTP 404 before any retrieval or generation call and contribute no retrieval scores. An applicable empty result scores zero. Case errors invalidate the affected aggregate and mark the run incomplete. Reports retain applicable, measured and failed counts.

Latency fields record query embedding, DBAPI vector query execution, and full retrieval through result materialization. SQL execution excludes subsequent fetch and hydration. Timing is observational and varies between runs.

### Verification and limits

`tests/test_rag_retrieval_units.py` covers the renderer, production chunking, mapping and hand-calculated metrics. `tests/test_rag_retrieval_evaluation.py` exercises the real PostgreSQL path, validates ownership and rank order, and compares two runs while excluding timing. The existing CI PostgreSQL service and pytest job support these tests. Without `TEST_DATABASE_URL`, pytest explicitly skips the PostgreSQL test and the CLI exits with a configuration error.

Provider-backed evaluation is deferred. Local hash results measure deterministic integration behavior on the synthetic corpus. PR3 will evaluate response correctness, citations and semantic abstention separately.

The isolated PostgreSQL/pgvector run completed all 14 cases at k=5 and a score floor of 0.05. PostgreSQL used pgvector 0.8.7 with no HNSW index in the test schema. Eight primary cases had recall and coverage 1.0, precision and novel precision 0.275, and MRR 1.0. The conflict case had recall and coverage 1.0, precision and novel precision 0.2, and MRR 1.0. Both authorization cases returned HTTP 404 before retrieval or generation. These scores describe the deterministic synthetic run.

Commands run from `backend/` with synthetic settings and disposable PostgreSQL and Redis:

- `python -B -m evaluation.retrieval_runner --k 5 --min-score 0.05` produced a complete JSON report.
- `python -B -m pytest -q -p no:cacheprovider tests/test_rag_retrieval_units.py tests/test_rag_retrieval_evaluation.py tests/test_rag_evaluation_schema.py tests/test_rag_evaluation.py tests/test_ai_rag_integration.py tests/test_document_grounded_qa.py --tb=short -rs` passed 132 tests with zero skips or failures, including final malformed-URL handling.
- `python -B -m pytest -q -p no:cacheprovider --tb=short -rs` passed 736 tests with zero skips or failures on the snapshot before the final malformed-URL guard. Two existing websockets deprecation warnings appeared. The full suite included real-cookie browser integration.
- With no test database URL, `python -B -m pytest -q -p no:cacheprovider tests/test_rag_retrieval_evaluation.py -rs` passed 6 tests and skipped the one real PostgreSQL test. Missing or malformed URLs gave CLI exit code 2.
- `python -m ruff check .`, `python -m ruff format --check .` and `git diff --check` passed. The legacy full-report comparison passed against the unchanged baseline.

Hosted CI was not run for these local changes.

## PR3 answer evaluation

Run the following from backend/ with the synthetic environment and loopback TEST_DATABASE_URL documented for PR2:

~~~powershell
python -B -m evaluation.answer_runner
~~~

A real provider key is unnecessary. The application settings accept the synthetic placeholder shown above. Tests initialize that placeholder when absent. The runner only supports a deterministic SDK fake and local embeddings. It reuses PR2's disposable PostgreSQL schema, authenticated PDF upload, mapping and authorization probe. An evaluation-only rate limit accommodates all synthetic requests on one local IP. The CLI rejects absent, malformed or non-loopback test database URLs. It emits JSON to stdout and returns 2 for invalid CLI configuration or 1 for an incomplete execution or evaluator contract failure.

### Rubric and controlled assertions

The versioned document_answer_rubric_v1.json sidecar binds its ordered 14 cases to PR1 by canonical dataset SHA-256. Each fact has a stable ID, a typed value, a required flag and alternative sufficient evidence groups. Each group is a conjunction of logical document/passage references. Monetary amounts are Decimal in the named currency's major units. Date facts use ISO dates. Boolean facts encode polarity. Equations represent the stated relation with Decimal operands and the applicable currency and accounting period. A causal relationship uses two controlled identifiers in the form cause explains effect. The loader validates references, checks equation consistency and rejects mismatched or incomplete rubrics. Semantic sufficiency of annotated groups remains a rubric authoring decision.

The controlled grammar accepts one fact per line, for example:

~~~text
closing-balance: 1,350.00 EUR @ 2025-01
closing-date: 2025-01-31
includes-refunds: false
payments-equal-expenses: 250 = 250 EUR @ 2025-01
revenue-cash-relationship: uncollected-revenue explains revenue-cash-gap
~~~

The numeric grammar accepts an optional sign, comma thousands grouping and dot decimals. Supported negation is an explicit not prefix before a typed value. The grader treats recognizable wrong values, polarity, currency, period and additional structured claims as failures. Prose or attribution outside the grammar requires review. Clearly detected contradictions still fail if the answer also contains unclassified text. Semantic metrics whose numerator may depend on unclassified text remain null. This grammar is for fixtures and leaves the application prompt and public API intact.

Q02 requires the two requested categories and records the total as optional corroboration. Q04 requires both documents for the equality. Q05 requires the three amounts and the explanation that uncollected recognized revenue accounts for the difference. The relationship's sufficient evidence group includes the recognized revenue, cash receipts and terminology passages. Q09 excludes the USD distractor from sufficient evidence. Q13 records two separate negatives. Q14 requires the four amounts and the reconciliation using account evidence. Other corroborating documents are optional for its citations.

### Metrics and report interpretation

The harness observes the exact context supplied to the SDK, cross-checks its references and text against persisted authorized chunks, and validates the identity of all public sources. It grades the delivered response separately from the draft decoded from the actual SDK completion and the parsed result. Missing or invalid completions cannot pass draft evaluation. Raw context and answers stay in memory. The report includes bounded outcomes, hashes and counts.

| Metric | Definition |
| --- | --- |
| Answer correctness | 1 when every required fact is asserted correctly with no detected contradiction or unsupported additional fact. 0 for a demonstrably wrong or incomplete controlled answer or an improper abstention. Null for unresolved semantic review. |
| Required-fact completeness | Correct distinct required facts divided by all required facts |
| Citation presence | 1 if at least one citation is published on a case expecting an answer, otherwise 0 |
| Citation validity | Distinct published citations matching authorized persisted identities in the actual model context divided by distinct published citations |
| Citation precision | Distinct valid citations contributing to a complete support group of a correctly asserted fact divided by distinct published citations |
| Claim support | Distinct asserted facts with complete cited support divided by evaluable distinct factual assertions, including wrong or unsupported additional assertions |
| Citation completeness | Correctly asserted required facts with complete cited support divided by all required facts |
| Abstention correctness | Q06/Q07/Q12 require abstained or insufficient_evidence, the abstention flag, a known safe public message and zero used citations |
| Authorization | Q10/Q11 require HTTP 404 with the exact generic error body and zero retrieval and generation calls |

Citation precision and validity are null when no citations are published. Identical references are counted once. Each sufficient group requires full coverage of every passage. Overlapping chunk spans are unioned, including when one group spans documents. Presence and validity do not establish claim support. The API does not expose claim-to-citation attribution, so the evaluator checks possible support from the set of cited chunks. It cannot attribute individual sentences to individual citations.

Q08 is tracked separately from ordinary abstention. The draft test requires both EUR 300 and EUR 350 and no authoritative choice. A unilateral choice or invented reconciliation fails the draft rubric. The production parser replaces the draft on abstention, so the public conflict explanation is unobservable. A fabricated draft that is discarded does not count as publicly delivered. Provider errors and invalid SDK JSON produce execution_error grades rather than successful abstentions.

Baseline aggregates use only the 14 baseline scenarios and report applicable and evaluated counts. A mean stays null for an incomplete population. Adversarial results are separate. The evaluator contract passes if all scenarios execute and match their expected grades, including deliberate failures, review outcomes and injected provider errors. An unexpected infrastructure or generation error makes the run incomplete. The report omits the former report_valid flag. Consumers can use execution completeness, evaluator contract and authorization results as separate checks. Authorization has its own gate. Expected injected errors are scenario outcomes rather than infrastructure failures.

**Passing deterministic fake-model evaluation does not demonstrate the answer quality of GPT-4o or any real provider.** Model quality is explicitly unmeasured and the quality threshold is null. Provider-backed evaluation and free-form semantic grading are deferred.

### PR3 verification

- Two invocations of python -B -m evaluation.answer_runner against separate schemas returned byte-identical JSON. The run completed 28 scenarios with zero execution failures and no skips. The 14 baseline cases passed, including eight correct and fully supported controlled answers, three public abstentions, a separate conflict case and two authorization rejections.
- The adversarial cases detected wrong currency and period, negation, an invented detail, irrelevant or incomplete citations, unilateral conflict resolution and a foreign reference. Ambiguous prose required review. The runner distinguished a discarded fabricated draft from its safe public response, deduplicated references and treated malformed JSON and provider failure as expected execution_error grades.
- The focused run used python -B -m pytest -q -p no:cacheprovider tests/test_rag_answer_metrics.py tests/test_rag_answer_evaluation.py tests/test_rag_evaluation_schema.py tests/test_rag_evaluation.py tests/test_rag_retrieval_units.py tests/test_rag_retrieval_evaluation.py tests/test_document_grounded_qa.py tests/test_ai_rag_integration.py --tb=short -rs. Result: 165 passed, zero failures or skips with PostgreSQL/pgvector.
- Running only the two PR3 test files without TEST_DATABASE_URL and without a provider key in the environment returned 31 passed and 2 PostgreSQL skips.
- PR2's before and after JSON matched after excluding measured latency and the working-tree dirty flag. The legacy baseline also matched. The PR2 invalid-k diagnostic was corrected to ASCII.
- Ruff lint, Ruff format check and git diff --check passed.
- The final full backend run used python -B -m pytest -q -p no:cacheprovider --tb=short -rs with disposable PostgreSQL and Redis and COOKIE_BROWSER_REQUIRED=1. It passed 770 tests with zero skips or failures and two existing websockets deprecation warnings.

### PR #19 review follow-up

Rubric version 1.1.0 adds the required Q05 causal relationship. With all three amounts correct, both missing causality and a wrong controlled cause fail answer correctness. Correct causality without complete support fails citation completeness. Unsupported free-form causal phrasing still requires review.

Q08 and the Q06 discarded-draft diagnostic now consume the actual SDK completion. The regression tests replace a configured correct conflict draft with incomplete content, change the abstention flag, and inject malformed or absent payloads. The tests also replace a configured Q06 fabrication with an empty captured draft and verify that the diagnostic does not fire.

The deterministic CLI completed 30 scenarios, with all 14 baselines satisfying the evaluator contract. The eight baseline answers retained means of 1.0 for factual and citation metrics. Ordinary abstention remained 3/3, with Q08 assessed separately, and authorization remained 2/2. The 16 adversarial scenarios produced 10 detected failures, 3 passes, 1 review and 2 expected error grades. PR2's stable report matched after excluding timings and Git metadata.
- Review verification: 174 focused tests and 779 full backend tests passed with zero failures or skips using isolated PostgreSQL/pgvector and Redis. The full run emitted two existing websockets deprecation warnings. Ruff, formatting and diff checks passed.

## PR4 versioned regression baselines

The independently versioned retrieval_v1.json and answer_v1.json files live in backend/evaluation/baselines/. Both use schema, normalization and metric contract version 1. The files contain a canonical SHA-256 excluding the digest field, source commit and runtime provenance, a compatibility identity, normalized cases and independently checked aggregates. The financial evaluation baseline is separate.

### Compatibility and comparison

Both contracts bind the dataset schema/version and canonical digest, corpus version and document digests, PDF renderer, embedding backend/model/dimensions, effective k and score floor, chunk geometry, PostgreSQL backend, pgvector version and HNSW presence. Answer evaluation also binds the rubric and the controlled SDK stimuli, including selected documents, expected grade and injected faults. It records the observed generation parameters. A digest of the whole evaluator source is deliberately excluded from compatibility. Changes to evaluator code are subject to comparison.

The adapter validates required fields, unique case/scenario keys, scope, execution, authorization and aggregate arithmetic. JSON duplicate keys and nonfinite values are rejected. Booleans are rejected in numeric positions. Missing, null and zero are distinct. PR2's unanswerable diagnostic cases retain null relevance metrics, and Q10/Q11 retain separate authorization contracts. PR3's expected adversarial failures and injected provider errors pass only when the observed grade matches the reviewed expectation. Q08 retains separate draft diagnostics and an unobservable public explanation on abstention. Offline mode requires zero provider calls and leaves the model-quality threshold null.

Per-case decreases gate before aggregate decreases. The absolute numeric tolerance is 1e-12 for normalized metrics only. Configuration, counts, masks and contract decisions compare exactly. Improvements are informational. Changes to ranks, prompt hashes and other bounded diagnostics are warnings when the contracts and metrics are preserved. Timing and Git metadata do not affect comparisons.

The comparator takes two normalized documents, including candidate artifacts written by the launcher:

~~~text
python -B -m evaluation.compare_baseline evaluation/baselines/retrieval_v1.json path/to/retrieval.report.json
~~~

Exit codes are 0 for pass with optional warnings, 1 for a regression or hard contract failure, 2 for invalid input, and 3 for incompatible configurations. Failed comparisons include categorized JSON differences.

### CI, trusted base and artifacts

From backend/, with the disposable test database settings documented above:

~~~text
python -B -m evaluation.baseline_suite run --base-ref <trusted-40-character-git-sha> --output <new-output-directory>
~~~

The existing backend CI job runs this after pytest. PostgreSQL uses the pgvector image digest recorded below. Retrieval and answer evaluation run sequentially in separate subprocesses. Each owns a temporary schema and upload directory. Avoid running pytest or another evaluation against the same database concurrently because the existing cleanup tests observe the set of evaluation schemas. When working locally, dedicate a database to each concurrent run. Only synthetic settings and a loopback TEST_DATABASE_URL are used. Redis serves the surrounding backend suite.

On pull requests, CI passes the event's base SHA. The launcher reads approved baselines with git show from that exact commit and rejects a candidate that replaces those files. On pushes to master, the merged SHA is the trusted source. The initial bootstrap exception is confined to the verified pre-baseline commit 5a388bedbc66a1e6283db5ab10baa46ce1489b95. For that base the launcher regenerates trusted reports from a temporary detached worktree and checks the proposed bootstrap files in both comparison directions before grading the candidate. Missing baselines at any other base fail closed.

The rag-evaluation artifact includes retrieval.report.json and answer.report.json, which are allowlisted normalized projections of the source reports, plus per-run execution.json and comparison JSON. Reduced failures produce bounded error categories. Raw stdout/stderr, DB URLs, prompts, answers, vectors and documents are excluded. CI uploads diagnostics with always() and any blocking result fails the backend job.

### Bootstrap and intentional promotion

The initial files originate from two sequential retrieval/answer pairs run at the clean merged commit 5a388bedbc66a1e6283db5ab10baa46ce1489b95. The environment was Linux x86_64 in the python:3.12 image with manifest digest sha256:cad37dd20c7cac861af9003af8796d03ea7a998ec1e3a664429740fc9d7d2691 and Python 3.12.16. Development dependencies were installed using the existing CI constraints file. The database was PostgreSQL 16.15 and pgvector 0.8.7 with no HNSW index in the evaluator schema. The PostgreSQL image is pinned in CI to pgvector/pgvector@sha256:7b822b0aac60967beb1ea5e576b8602c94c300a157d187f385ae3e0da199b90a. This is Linux container evidence from the clean merge, with dependency digest recorded in both baseline files. Hosted CI separately validates the proposed bootstrap.

Run the unmodified retrieval and answer CLIs twice at the approved clean master commit. Keep the four source JSON reports and a dependency inventory outside the checkout. From a checkout with the same dataset, corpus, rubric and stimuli, run the explicit promotion command:

~~~text
python -B -m evaluation.baseline_suite promote --source-commit <verified-master-sha> --reports <directory-with-retrieval-1.json-retrieval-2.json-answer-1.json-answer-2.json> --python <source-python-version> --environment <source-platform> --dependencies <source-pip-freeze-file> --output <new-review-directory>
~~~

Promotion requires matching source SHA, clean source runs and reproducible normalized documents. Review the population, applicability, Q08, both authorization cases, artifact digests and environment before copying the results into a dedicated baseline update. Ordinary CI rejects changed baselines against the previously trusted ref. A future intentional dataset, rubric or stimulus change therefore requires an explicit review and promotion of a new reference. Automatic baseline updates on failure are excluded.

**A passing PR4 regression check demonstrates compatibility with the reviewed offline baseline. It does not establish real GPT-4o answer quality or AWS deployment readiness.**

### Implementation verification

- Both baseline inputs were repeated on the clean Linux source, and explicit promotion required identical normalized documents. The standalone runner commands are documented in the PR2 and PR3 sections.
- The CI-equivalent baseline suite passed both comparisons, including the trusted bootstrap and separate candidate execution.
- The comparator suite passed 46 tests, including out-of-scope results in a pre-normalized candidate. The focused regression suite covers the comparator, PR1-PR3 and Document Q&A.
- The full backend command python -B -m pytest -q -p no:cacheprovider --tb=short -rs --show-capture=no passed 824 tests before the final normalized-scope regression was added, with isolated PostgreSQL/pgvector, Redis and the real-cookie browser tests. Ruff lint, formatting, YAML placement and git diff --check passed.
