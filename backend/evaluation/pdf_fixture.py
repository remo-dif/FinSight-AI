"""Deterministic PDFs for the synthetic evaluation corpus."""

from pathlib import Path
from textwrap import wrap

from app.services.document_ingestion import DocumentIngestionService

RENDERER_VERSION = "winansi-wrapped-v1"


def render_pdf(text: str) -> bytes:
    lines = wrap(" ".join(text.split()), width=72, break_long_words=False, break_on_hyphens=False)
    if not lines or any(len(line) > 72 for line in lines):
        raise ValueError("Fixture text cannot be wrapped safely")
    pages = [lines[i : i + 48] for i in range(0, len(lines), 48)]
    references = " ".join(f"{4 + i * 2} 0 R" for i in range(len(pages)))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Count {len(pages)} /Kids [{references}] >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    for lines in pages:
        page_id = len(objects) + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>"
            ).encode()
        )
        escaped = [
            line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in lines
        ]
        stream = (
            "BT /F1 10 Tf 14 TL 40 750 Td "
            + " T* ".join(f"({line}) Tj" for line in escaped)
            + " ET"
        ).encode("cp1252")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream")
    payload = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(payload))
        payload.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        payload.extend(f"{offset:010d} 00000 n \n".encode())
    payload.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(payload)


async def verify_pdf(
    service: DocumentIngestionService, path: Path, original: str, anchors: list[str]
) -> str:
    extracted = await service.extract_document_text(path)
    normalized = " ".join(extracted.split())
    if normalized != " ".join(original.split()):
        raise ValueError("PDF round trip changed fixture text")
    if any(" ".join(anchor.split()) not in normalized for anchor in anchors):
        raise ValueError("PDF round trip lost an evidence anchor")
    return extracted
