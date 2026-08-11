"""Sales must not access unscoped internal business documents."""
import pytest
from fastapi import HTTPException

from portal.routes import business


class _Documents:
    async def find_one(self, _query):
        return {"_id": object(), "stored_name": "internal.pdf"}


class _Db:
    documents = _Documents()


@pytest.mark.anyio
async def test_sales_cannot_download_unscoped_business_document(monkeypatch):
    async def fake_db():
        return _Db()

    monkeypatch.setattr(business, "_get_db", fake_db)
    monkeypatch.setattr(business, "_oid", lambda _value: object())

    # Make the file appear to exist so code reaches auth check before 404
    class _AlwaysExistsPath:
        def __init__(self, *parts):
            self._parts = parts

        def exists(self):
            return True

    monkeypatch.setattr(business, "_DocPath", _AlwaysExistsPath)

    with pytest.raises(HTTPException) as exc:
        await business.docs_file("64b000000000000000000001", staff={"role": "sales"})

    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", ["sales", "creative"])
def test_unscoped_business_documents_reject_sales_and_creative_for_every_action(role):
    """Unassigned internal documents may not be read or mutated by these roles."""
    with pytest.raises(HTTPException) as exc:
        business._require_internal_document_access({"role": role})

    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", ["admin", "support", "finance"])
def test_unscoped_business_documents_allow_internal_staff(role):
    business._require_internal_document_access({"role": role})
