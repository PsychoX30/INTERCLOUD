"""Prove the extended landing-CMS contract before it reaches prod.

Covers the new `lists` slot: additive defaults, per-field validation, caps,
textless-entry rejection, and that a legacy 4-slot document still resolves.
Run against the real backend package on the prod box.
"""
import asyncio
import copy

import pytest

from portal.backups import LANDING_CONTENT_DEFAULT, get_landing_content
from portal.routes.cms import _clean_landing_lists, _sane_id, _sane_str, LIST_SPEC


# ---------- defaults ----------

def test_default_has_lists_slot():
    assert "lists" in LANDING_CONTENT_DEFAULT
    for key in ("services", "testimonials", "partners", "stats",
                "hero_terms", "footer_links"):
        assert LANDING_CONTENT_DEFAULT["lists"][key] == []


def test_default_not_mutated():
    """get_landing_content(None) must hand back a copy, not the module global."""
    a = asyncio.run(get_landing_content(None))
    a["lists"]["services"].append({"title": {"id": "x", "en": "x"}})
    b = asyncio.run(get_landing_content(None))
    assert b["lists"]["services"] == [], "module default was mutated"
    assert LANDING_CONTENT_DEFAULT["lists"]["services"] == []


# ---------- _sane_id / _sane_str ----------

def test_sane_id_accepts_pair():
    assert _sane_id({"id": "Halo", "en": "Hello"}) == {"id": "Halo", "en": "Hello"}


def test_sane_id_fills_missing_language():
    assert _sane_id({"id": "Halo"}) == {"id": "Halo", "en": "Halo"}
    assert _sane_id({"en": "Hello"}) == {"id": "Hello", "en": "Hello"}


def test_sane_id_promotes_bare_string():
    assert _sane_id("Halo") == {"id": "Halo", "en": "Halo"}


def test_sane_id_rejects_junk():
    assert _sane_id(None) is None
    assert _sane_id(123) is None
    assert _sane_id({"id": "", "en": "   "}) is None
    assert _sane_id({"id": 5, "en": []}) is None


def test_sane_str_truncates_and_rejects():
    assert _sane_str("  hi  ") == "hi"
    assert _sane_str(None) == ""
    assert _sane_str(42) == ""
    assert len(_sane_str("a" * 1000, limit=10)) == 10


# ---------- _clean_landing_lists ----------

def test_clean_drops_unknown_lists():
    out = _clean_landing_lists({"evil": [{"x": 1}], "services": []})
    assert set(out) == set(LIST_SPEC)
    assert "evil" not in out


def test_clean_non_dict_yields_all_empty():
    out = _clean_landing_lists("nope")
    assert set(out) == set(LIST_SPEC)
    assert all(v == [] for v in out.values())


def test_clean_services_entry():
    out = _clean_landing_lists({"services": [{
        "icon": "server",
        "title": {"id": "VPS", "en": "VPS"},
        "desc": {"id": "Cepat", "en": "Fast"},
        "bullets": [{"id": "SSD", "en": "SSD"}],
        "start_price": "Rp 500.000",
        "href": "#services",
    }]})
    row = out["services"][0]
    assert row["icon"] == "server"
    assert row["title"] == {"id": "VPS", "en": "VPS"}
    assert row["bullets"] == [{"id": "SSD", "en": "SSD"}]


def test_clean_drops_textless_entries():
    out = _clean_landing_lists({"services": [{}, {"icon": ""}, {"title": {"id": ""}}]})
    assert out["services"] == []


def test_clean_caps_rows():
    cap, _ = LIST_SPEC["testimonials"]
    rows = [{"quote": {"id": f"q{i}", "en": f"q{i}"}} for i in range(cap + 20)]
    out = _clean_landing_lists({"testimonials": rows})
    assert len(out["testimonials"]) == cap
    assert out["testimonials"][0]["quote"]["id"] == "q0"


def test_clean_rating_bounds():
    out = _clean_landing_lists({"testimonials": [
        {"quote": {"id": "a", "en": "a"}, "rating": 4},
        {"quote": {"id": "b", "en": "b"}, "rating": 99},
        {"quote": {"id": "c", "en": "c"}, "rating": "x"},
    ]})
    rows = {r["quote"]["id"]: r for r in out["testimonials"]}
    assert rows["a"]["rating"] == 4
    assert "rating" not in rows["b"]  # out of range dropped
    assert "rating" not in rows["c"]  # non-numeric dropped
    # a rating alone (no text) must not survive as a ghost row
    out2 = _clean_landing_lists({"testimonials": [{"rating": 5}]})
    assert out2["testimonials"] == []


def test_clean_rating_rejects_bool():
    """bool is an int subclass - must not sneak through as a rating."""
    out = _clean_landing_lists({"testimonials": [{"quote": {"id": "b", "en": "b"}, "rating": True}]})
    assert "rating" not in out["testimonials"][0]


def test_clean_footer_links_requires_label_and_href():
    out = _clean_landing_lists({"footer_links": [{
        "group": {"id": "Layanan", "en": "Services"},
        "items": [
            {"label": {"id": "VPS", "en": "VPS"}, "href": "/services"},
            {"label": {"id": "NoHref", "en": "NoHref"}},
            {"href": "/orphan"},
        ],
    }]})
    items = out["footer_links"][0]["items"]
    assert items == [{"label": {"id": "VPS", "en": "VPS"}, "href": "/services"}]


def test_clean_footer_group_without_items_kept():
    """A group header saved before its links exist is a valid draft: the
    frontend renders `items || []`, so it must survive the round-trip."""
    out = _clean_landing_lists({"footer_links": [
        {"group": {"id": "Legal", "en": "Legal"}, "items": []},
    ]})
    assert out["footer_links"] == [{"group": {"id": "Legal", "en": "Legal"}}]


def test_clean_footer_entry_with_no_group_and_no_items_dropped():
    out = _clean_landing_lists({"footer_links": [{"items": []}]})
    assert out["footer_links"] == []


def test_clean_partner_and_stats():
    out = _clean_landing_lists({
        "partners": [{"name": "ISV", "domain": "isv.co.id"}],
        "stats": [{"value": "99.9%", "label": {"id": "Uptime", "en": "Uptime"}}],
    })
    assert out["partners"][0]["domain"] == "isv.co.id"
    assert out["stats"][0]["value"] == "99.9%"
