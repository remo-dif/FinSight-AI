# 5. UX/UI Design

## Information Architecture

- Dashboard: net cash flow, spending categories, anomalies, recurring payments, and recent transactions.
- Assistant: conversational financial analytics with cited tool results.
- Uploads: CSV/document upload progress, validation state, parsed summaries.
- Reports: generated monthly summaries and export-ready insights.
- Settings: profile, security, API sessions, and data controls.

## Primary User Journey

1. User signs in.
2. User uploads transactions or financial documents.
3. System validates, parses, normalizes, categorizes, and stores data.
4. Dashboard updates with spending and anomaly insights.
5. User asks the assistant questions.
6. Assistant routes through tools and returns reviewed analysis.
7. User generates a monthly report.

## Design Tokens

- Radius: 8px for repeated cards and compact panels.
- Typography: restrained dashboard scale optimized for scanning.
- Color: neutral base with green, blue, amber, and red semantic accents.
- Density: SaaS operations layout, not a marketing landing page.

## Accessibility

- Keyboard navigable controls.
- Semantic regions.
- Sufficient color contrast.
- Form labels and live upload states.
