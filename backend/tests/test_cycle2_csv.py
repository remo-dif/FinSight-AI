import pytest
from fastapi import HTTPException

from app.services.document_ingestion import DocumentIngestionService
from app.services.ingestion import IngestionService


@pytest.mark.parametrize("parser", [IngestionService, DocumentIngestionService])
@pytest.mark.parametrize("value", ["NaN", "sNaN", "-NaN", "Infinity", "-Infinity", "+Infinity"])
@pytest.mark.parametrize("explicit_category", [True, False])
def test_nonfinite_amount_is_rejected_before_categorization(parser, value, explicit_category):
    class NeverCategorize:
        def categorize(self, *args):
            pytest.fail("Non-finite money reached categorization")
    service = parser(NeverCategorize())
    category = ",category" if explicit_category else ""
    suffix = ",Groceries" if explicit_category else ""
    payload = f"date,merchant,amount,currency{category}\n2025-01-01,Synthetic,{value},EUR{suffix}\n".encode()
    with pytest.raises(HTTPException) as exc:
        service.parse_csv(payload)
    assert exc.value.status_code == 400
    assert "line 2" in exc.value.detail
