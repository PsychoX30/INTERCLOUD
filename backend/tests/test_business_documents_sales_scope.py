"""Sales must not access unscoped internal business documents."""
import pytest
from bson import ObjectId
from fastapi import HTTPException
from unittest.mock import AsyncMock

from portal.routes import business


class _Documents:
    async def find_one(self, _query):
        return {"_id": object(), "stored_name": "internal.pdf"}


class _Db:
    documents = _Documents()


@pytest.mark.anyio
async def test_sales_cannot_download_unscoped_business_document(monkeypatch, tmp_path):
    """Sales cannot read a legacy common document that is neither shared nor owned."""
    did = ObjectId()
    stored_name = f"{did}.pdf"
    (tmp_path / stored_name).write_bytes(b"%PDF-1.4")

    class _Documents:
        async def find_one(self, _query):
            return {"_id": did, "stored_name": stored_name, "owner_id": None,
                    "shared": False, "content_type": "application/pdf", "filename": "x.pdf"}

    class _Db:
        documents = _Documents()

    monkeypatch.setattr(business, "_get_db", AsyncMock(return_value=_Db()))
    monkeypatch.setattr(business, "_oid", lambda _value: did)
    monkeypatch.setattr(business, "DOCS_DIR", tmp_path)

    with pytest.raises(HTTPException) as exc:
        await business.docs_file(str(did), staff={"role": "sales", "id": "sales1"})

    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", ["sales", "creative"])
def test_unscoped_business_documents_reject_sales_and_creative_for_read(role):
    """Legacy common documents (no owner, not shared) are invisible to sales/creative."""
    doc = {"owner_id": None, "shared": False, "share_with": {"users": [], "divisions": [], "roles": []}}
    assert business._doc_can_read({"role": role}, doc) is False


@pytest.mark.parametrize("role", ["admin", "support", "finance"])
def test_unscoped_business_documents_allow_internal_staff(role):
    business._require_internal_document_access({"role": role})
