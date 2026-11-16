"""A document saved by the OLD CMS (no `lists` key) must still resolve.

This is the migration risk: prod already has `settings.landing_content` rows
written by the previous contract. get_landing_content() must not KeyError and
must hand every caller the full shape.
"""
import asyncio

import pytest

from portal.backups import get_landing_content, LANDING_CONTENT_DEFAULT


class _FakeCursor:
    """Motor's find_one returns an awaitable, so the fake must be awaitable."""

    def __init__(self, doc):
        self._doc = doc

    def __await__(self):
        async def _inner():
            return self._doc

        return _inner().__await__()


class _FakeCollection:
    def __init__(self, doc):
        self._doc = doc

    def find_one(self, *_a, **_k):
        return _FakeCursor(self._doc)


class _FakeDB:
    def __init__(self, doc):
        self.settings = _FakeCollection(doc)


def _resolve(doc):
    return asyncio.run(get_landing_content(_FakeDB(doc)))


def test_legacy_doc_without_lists():
    """Exactly what prod stores today: 4 slots, empty values."""
    doc = {"value": {"overrides": {}, "faqs": [], "contact": {}, "images": {}}}
    got = _resolve(doc)
    assert got["overrides"] == {}
    assert got["lists"] == {k: [] for k in LANDING_CONTENT_DEFAULT["lists"]}


def test_legacy_doc_preserves_content():
    doc = {"value": {
        "overrides": {"hero.h1a": {"id": "Halo", "en": "Hello"}},
        "faqs": [{"q": {"id": "a", "en": "a"}, "a": {"id": "b", "en": "b"}}],
        "contact": {"phone": "+62"},
        "images": {"hero_main": {"url": "https://x/y.jpg", "alt_id": "", "alt_en": ""}},
    }}
    got = _resolve(doc)
    assert got["overrides"]["hero.h1a"]["id"] == "Halo"
    assert len(got["faqs"]) == 1
    assert got["contact"]["phone"] == "+62"
    assert got["images"]["hero_main"]["url"] == "https://x/y.jpg"
    assert got["lists"]["services"] == []


def test_partial_lists_merged():
    """A doc saved by a newer CMS with only some list keys set."""
    doc = {"value": {"lists": {"partners": [{"name": "X", "domain": "x.co.id"}]}}}
    got = _resolve(doc)
    assert got["lists"]["partners"] == [{"name": "X", "domain": "x.co.id"}]
    assert got["lists"]["services"] == []


def test_malformed_lists_ignored():
    """lists saved as a string must not crash the endpoint."""
    doc = {"value": {"lists": "garbage"}}
    got = _resolve(doc)
    assert got["lists"] == {k: [] for k in LANDING_CONTENT_DEFAULT["lists"]}


def test_list_value_not_a_list_ignored():
    doc = {"value": {"lists": {"services": {"nope": 1}}}}
    got = _resolve(doc)
    assert got["lists"]["services"] == []


def test_no_settings_row_at_all():
    got = _resolve(None)
    assert got["lists"] == {k: [] for k in LANDING_CONTENT_DEFAULT["lists"]}
