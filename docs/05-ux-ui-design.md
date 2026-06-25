# 5. UX/UI Design

## Information Architecture

- Investigation workspace: first-screen case review surface for suspicious transaction activity.
- Operations overview: compact metrics, risk posture, case status, and analyst-ready signals.
- Alert queue: prioritized suspicious transactions with merchant, risk, amount, and review state.
- Risk drivers: charted fraud signals for quick triage.
- Entity graph: relationship view for accounts, merchants, devices, cards, and linked identities.
- Evidence timeline: chronological case evidence for review and escalation.
- Case decision: structured decision panel for approve, monitor, escalate, or block outcomes.
- Analyst session: authentication panel scoped to the current analyst.
- Investigation copilot: conversational analysis surface for case questions and tool-backed answers.
- Evidence ingestion: secure upload flow for statements, screenshots, and supporting files.

## Primary User Journey

1. User signs in.
2. User reviews suspicious transaction alerts in the operational workspace.
3. User checks risk drivers, entity relationships, and evidence history.
4. User uploads supporting evidence or financial documents.
5. System validates, parses, normalizes, categorizes, and stores data.
6. User asks the investigation copilot case-specific questions.
7. Assistant routes through tools and returns reviewed analysis.
8. User records a decision or escalates the case.

## Design Tokens

- Radius: 8px for repeated cards and compact panels.
- Typography: restrained dashboard scale optimized for scanning.
- Color: neutral base with green, blue, amber, and red semantic accents.
- Density: SaaS operations layout, not a marketing landing page.
- Layout: full-width operational shell with constrained inner content and no nested card stacks.
- Controls: icon-led actions, compact buttons, clear upload affordances, and stable table/chart dimensions.

## Recent UI Refresh

The June 2026 UI refresh moved the product from a general personal-finance assistant dashboard to
a fraud-investigation workspace. The first viewport now communicates the actual product function:
investigating suspicious financial activity. The experience is designed for repeated analyst use,
with dense scanning surfaces, restrained visual hierarchy, and domain-specific labels instead of
marketing-style copy.

The key visible sections are:

- `Investigate suspicious transaction activity`
- `Operations overview`
- `Alert queue`
- `Risk drivers`
- `Entity graph`
- `Evidence timeline`
- `Case decision`
- `Analyst session`
- `Investigation copilot`
- `Evidence ingestion`

## Accessibility

- Keyboard navigable controls.
- Semantic regions.
- Sufficient color contrast.
- Form labels and live upload states.
- Playwright coverage verifies the main workspace headings on desktop and mobile viewports.
