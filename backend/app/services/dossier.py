"""Canonical, owner-scoped case dossier snapshots and PDF rendering."""

import hashlib
import io
import json
import textwrap
import unicodedata
from datetime import UTC, date, datetime
from decimal import Decimal
from html import escape
from pathlib import Path
from typing import Any
from uuid import UUID

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import AuditLog
from app.models.case import CaseDocumentLink, CaseFollowUp, CaseNote
from app.models.finance import Transaction, UploadedFile
from app.models.user import User
from app.repositories.cases import CaseRepository
from app.services.risk_signals import RiskSignalConfig, evaluate_risk_signals

FORMAT_VERSION = "2"
MAX_SIGNAL_TRANSACTIONS = 5000
DISCLAIMER = (
    "Rule-based indicators only. This document does not determine that fraud occurred. "
    "The displayed hash identifies the canonical JSON; it is not a digital signature "
    "or proof of this PDF's authenticity."
)


def _utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    # PostgreSQL returns aware datetimes. SQLite test fixtures lose timezone metadata.
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            unicodedata.normalize("NFC", str(key)): _canonical_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Dossier contains a non-finite monetary value")
        return format(value, "f")
    if isinstance(value, float):
        raise TypeError("Dossier cannot serialize binary floating-point values")
    if value is None or isinstance(value, (bool, int)):
        return value
    raise TypeError(f"Unsupported dossier value: {type(value).__name__}")


def canonical_bytes(snapshot: dict[str, Any]) -> bytes:
    return json.dumps(
        _canonical_value(snapshot),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def build_snapshot(db: Session, case_id: UUID, owner_id: UUID) -> dict[str, Any] | None:
    """Call inside a repeatable-read transaction; never include export events."""
    record = CaseRepository(db).get_for_user(case_id, owner_id)
    if record is None:
        return None
    case, transaction, assignee = record
    rows = list(
        db.scalars(
            select(Transaction)
            .where(Transaction.user_id == owner_id)
            .order_by(Transaction.posted_at, Transaction.id)
            .limit(MAX_SIGNAL_TRANSACTIONS + 1)
        )
    )
    if len(rows) > MAX_SIGNAL_TRANSACTIONS:
        signal_status = "unavailable: owner transaction history exceeds 5000 records"
        signals: list[dict[str, Any]] = []
    else:
        signal_status = "evaluated from current owner transaction history with rule version 1"
        signals = [
            signal.model_dump(mode="python")
            for signal in evaluate_risk_signals(
                rows, RiskSignalConfig(max_transaction_references=MAX_SIGNAL_TRANSACTIONS)
            )
            if (
                signal.transaction_ids[-1] == case_id
                if signal.signal_type == "amount_deviation"
                else case_id in signal.transaction_ids
            )
        ]
    signals.sort(key=lambda item: (item["observed_at"], item["signal_type"], item["signal_id"]))

    notes = list(
        db.execute(
            select(CaseNote, User)
            .outerjoin(User, User.id == CaseNote.author_id)
            .where(CaseNote.case_id == case_id)
            .order_by(CaseNote.created_at, CaseNote.id)
        )
    )
    follow_ups = list(
        db.execute(
            select(CaseFollowUp, User)
            .join(User, User.id == CaseFollowUp.actor_id)
            .where(CaseFollowUp.case_id == case_id)
            .order_by(CaseFollowUp.created_at, CaseFollowUp.revision, CaseFollowUp.id)
        )
    )
    evidence = list(
        db.execute(
            select(CaseDocumentLink, UploadedFile)
            .join(UploadedFile, UploadedFile.id == CaseDocumentLink.uploaded_file_id)
            .where(CaseDocumentLink.case_id == case_id, UploadedFile.user_id == owner_id)
            .order_by(CaseDocumentLink.linked_at, CaseDocumentLink.uploaded_file_id)
        )
    )
    audit = list(
        db.scalars(
            select(AuditLog)
            .where(
                AuditLog.action.like("case.%"),
                ~AuditLog.action.like("case.dossier_export%"),
                AuditLog.metadata_json["case_id"].as_string() == str(case_id),
            )
            .order_by(AuditLog.created_at, AuditLog.id)
        )
    )
    return {
        "dossier_format_version": FORMAT_VERSION,
        "case": {
            "id": case_id,
            "status": case.status,
            "revision": case.revision,
            "assignee": assignee.full_name if assignee else None,
            "decision": case.decision,
            "decision_reason": case.decision_reason,
            "created_at": case.created_at,
            "updated_at": case.updated_at,
        },
        "transaction": {
            "id": transaction.id,
            "posted_at": transaction.posted_at,
            "merchant": transaction.merchant,
            "description": transaction.description,
            "amount": transaction.amount,
            "currency": transaction.currency,
            "category": transaction.category,
            "source": transaction.source,
        },
        "risk_signals": {"status": signal_status, "results": signals},
        "evidence_scope": "Only documents explicitly linked to this case are listed.",
        "evidence": [
            {
                "id": upload.id,
                "filename": upload.filename,
                "content_type": upload.content_type,
                "uploaded_at": upload.created_at,
                "extracted_text_status": upload.status,
                "linked_at": link.linked_at,
                "linked_by": link.linked_by,
            }
            for link, upload in evidence
        ],
        "notes": [
            {
                "id": note.id,
                "author": author.full_name if author else "Former analyst",
                "created_at": note.created_at,
                "content": note.content,
            }
            for note, author in notes
        ],
        "follow_ups": [
            {
                "id": item.id,
                "revision": item.revision,
                "author": author.full_name,
                "created_at": item.created_at,
                "action": item.action,
                "reason": item.reason,
                "previous_status": item.previous_status,
                "resulting_status": item.resulting_status,
            }
            for item, author in follow_ups
        ],
        "audit_events": [
            {
                "id": event.id,
                "action": event.action,
                "actor_id": event.user_id,
                "created_at": event.created_at,
                "metadata": event.metadata_json,
            }
            for event in audit
        ],
    }


def _font() -> str:
    import reportlab

    name = "DossierVera"
    if name not in pdfmetrics.getRegisteredFontNames():
        path = Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"
        pdfmetrics.registerFont(TTFont(name, str(path)))
    return name


def render_pdf(
    snapshot: dict[str, Any], digest: str, exporter: str, generated_at: datetime
) -> bytes:
    """Render escaped snapshot text. Footer is drawn on every page."""
    font = _font()
    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "DossierBody",
        parent=styles["Normal"],
        fontName=font,
        fontSize=9,
        leading=13,
        splitLongWords=1,
        spaceAfter=6,
    )
    heading = ParagraphStyle(
        "DossierHeading", parent=normal, fontSize=13, leading=17, spaceBefore=14, spaceAfter=8
    )
    footer_style = ParagraphStyle(
        "DossierFooter", parent=normal, fontSize=7, leading=9, alignment=TA_CENTER
    )
    story: list[Any] = []

    def line(label: str, value: Any) -> None:
        display = "Not recorded" if value is None else str(_canonical_value(value))
        if len(display) <= 240:
            story.append(Paragraph(f"<b>{escape(label)}</b>: {escape(display)}", normal))
            return
        story.append(Paragraph(f"<b>{escape(label)}</b>:", normal))
        for chunk in textwrap.wrap(
            display,
            width=120,
            break_long_words=True,
            break_on_hyphens=False,
            replace_whitespace=False,
            drop_whitespace=False,
        ):
            story.append(Paragraph(escape(chunk), normal))

    def section(title: str) -> None:
        story.append(Paragraph(escape(title), heading))

    case = snapshot["case"]
    section("Case dossier")
    for label, value in (
        ("Case ID", case["id"]),
        ("Status", case["status"]),
        ("Assignee", case["assignee"]),
        ("Format version", FORMAT_VERSION),
        ("Generated UTC (not hashed)", _utc(generated_at)),
        ("Exporter (not hashed)", exporter),
    ):
        line(label, value)
    section("Transaction details")
    for label, value in snapshot["transaction"].items():
        line(label.replace("_", " ").title(), value)
    section("Risk signals")
    line("Evaluation", snapshot["risk_signals"]["status"])
    if not snapshot["risk_signals"]["results"]:
        line("Results", "None recorded for this case")
    for signal in snapshot["risk_signals"]["results"]:
        line("Signal", f"{signal['signal_type']} ({signal['risk_level']})")
        line("Explanation", signal["explanation"])
        line(
            "Supporting values",
            json.dumps(_canonical_value(signal["evidence"]), ensure_ascii=False, sort_keys=True),
        )
        line(
            "Thresholds",
            json.dumps(_canonical_value(signal["thresholds"]), ensure_ascii=False, sort_keys=True),
        )
    section("Evidence list")
    line("Scope", snapshot["evidence_scope"])
    if not snapshot["evidence"]:
        line("Documents", "None")
    for item in snapshot["evidence"]:
        line(
            "Document",
            f"{item['filename']} | {item['content_type']} | {_utc(item['uploaded_at'])} | "
            f"{item['extracted_text_status']} | linked {_utc(item['linked_at'])} by "
            f"{item['linked_by'] or 'Former analyst'}",
        )
    section("Notes and decision history")
    line("Initial decision", case["decision"])
    line("Initial reason", case["decision_reason"])
    if not snapshot["notes"] and not snapshot["follow_ups"]:
        line("History", "No notes or follow-ups")
    history = [
        (item["created_at"], str(item["id"]), "Note", f"{item['author']}: {item['content']}")
        for item in snapshot["notes"]
    ] + [
        (
            item["created_at"],
            str(item["id"]),
            "Follow-up",
            f"{item['author']}: {item['action']} | {item['previous_status']} → {item['resulting_status']} | {item['reason']}",
        )
        for item in snapshot["follow_ups"]
    ]
    for timestamp, _, label, value in sorted(history, key=lambda row: (row[0], row[1])):
        line(f"{label} {_utc(timestamp)}", value)
    section("Case audit trail summary")
    if not snapshot["audit_events"]:
        line("Events", "None")
    for item in snapshot["audit_events"]:
        line(
            "Event",
            f"{_utc(item['created_at'])} | {item['action']} | actor {item['actor_id']} | "
            f"{json.dumps(_canonical_value(item['metadata']), ensure_ascii=False, sort_keys=True)}",
        )

    output = io.BytesIO()
    document = SimpleDocTemplate(
        output, pagesize=A4, leftMargin=44, rightMargin=44, topMargin=42, bottomMargin=112
    )

    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        width, _ = A4
        canvas.setStrokeColor(colors.grey)
        canvas.line(44, 104, width - 44, 104)
        canvas.setFont(font, 7)
        canvas.drawCentredString(width / 2, 91, f"SHA-256 {digest} | Page {doc.page}")
        paragraph = Paragraph(escape(DISCLAIMER), footer_style)
        _, height = paragraph.wrap(width - 88, 70)
        paragraph.drawOn(canvas, 44, 78 - height)
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
