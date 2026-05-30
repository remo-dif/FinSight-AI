# 1. Requirements Analysis

## Product Goal

Personal Finance AI Assistant is a SaaS platform that helps users understand cash flow, detect anomalies, identify recurring payments, analyze uploaded financial documents, ask conversational questions, and generate reports.

## Functional Requirements

- User authentication with JWT, refresh tokens, bcrypt password hashing, and RBAC.
- Transaction ingestion from CSV and financial documents.
- Multimodal document handling for PDF, PNG, JPG, and JPEG.
- Transaction normalization, categorization, and storage.
- Financial analytics tools exposed only through controlled backend functions.
- Conversational AI with strict tool calling. The model never receives database credentials or direct SQL access.
- Personal RAG knowledge base over receipts, PDFs, and notes.
- Budget generation, anomaly detection, recurring payment detection, and report generation.
- Responsive dashboard, chat, upload, and report experiences.

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
- OCR support is implemented as a service boundary with pdfplumber, Pillow, and pytesseract dependencies, but deep bank-statement layout extraction should be extended per institution.

## Risks

- Financial hallucination risk is mitigated by tool-only data access and reviewer agent checks.
- File-upload attack surface is mitigated with extension, MIME, size, path, and parsing controls.
- Privacy risk is mitigated with audit logs, scoped queries, and planned field-level encryption for sensitive document text.
- Categorization accuracy requires iterative improvement using user corrections.
