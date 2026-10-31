# 1. Requirements Analysis

## Product Goal

FinSight-AI is a portfolio application for transaction analysis and investigation-case review. Its current chat answers financial queries using transaction tools. General document question answering, document citations and OCR are not implemented public capabilities.

## Functional Requirements

- User authentication with JWT, persisted refresh-token rotation and bcrypt password hashing. Role-check helpers exist; uploads enforce USER/ADMIN roles, while case, transaction and chat routes use active-user authentication and user ownership rather than a separate analyst-role policy.
- Explicit-currency transaction ingestion from CSV; PDF text extraction and embedding storage do not create transaction rows.
- PDF, PNG, JPG and JPEG upload validation. Text-based PDFs can be indexed; images currently produce a dimensions/metadata placeholder, not OCR text.
- Transaction normalization, categorization, and storage.
- Financial analytics tools exposed only through controlled backend functions.
- Financial chat with application-controlled keyword routing and tool execution. The model selects permitted financial claim IDs; it does not choose or execute database tools through function calling.
- Internal user-scoped RAG indexing/retrieval for uploaded text. Retrieval uses top-K similarity ranking without a minimum relevance threshold. General document answers, document citations and automatic indexing of case notes remain planned.
- Deterministic monthly summaries/comparisons, category/merchant spending, anomaly heuristics, repeated-charge estimates and budget estimates.
- Responsive investigation workspace, case controls, chat and upload experiences. Downloadable report generation is not a public endpoint.

## Non-Functional Requirements

- Typed API and frontend contracts.
- Modular boundaries suitable for production scaling.
- Auditability for authentication, uploads, and AI tool access.
- Containerized local development.
- CI pipeline for lint, tests, build, and security scan.

## Assumptions And Tradeoffs

- The repository starts as a portfolio-grade foundation, not a fully regulated banking product.
- Plaid/Open Banking integrations are deferred so the first version can focus on ingestion, analytics, and AI architecture.
- LangGraph is isolated behind an orchestration adapter so the graph can run with mocked LLMs in tests and real OpenAI calls in production.
- Text PDFs use pdfplumber and image validation uses Pillow. The container installs Tesseract, but no OCR call is wired into ingestion and pytesseract is not a declared application dependency. Scanned-PDF OCR and institution-specific statement extraction remain planned.
- Upload extraction and embedding calls run within the request lifecycle, outside database persistence transactions; a background worker queue is not implemented.

## Risks

- Financial hallucination risk is mitigated by tool-only data access and reviewer agent checks.
- File-upload attack surface is mitigated with extension, MIME, size, path, and parsing controls.
- Privacy risk is mitigated with audit logs, scoped queries, and planned field-level encryption for sensitive document text.
- Categorization accuracy requires iterative improvement using user corrections.
