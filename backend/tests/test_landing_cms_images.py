"""TDD RED: Landing CMS image overrides.

New feature: `images` field in landing_content allows admin to override
hardcoded image URLs (hero, infra cards) via CMS without base64 bloat.

Schema:
  {
    "overrides": {...},
    "faqs": [...],
    "contact": {...},
    "images": {
      "hero_main": {"url": "...", "alt_id": "...", "alt_en": "..."},
      ...
    }
  }

All fields optional. Empty url = use hardcoded default.
"""
from __future__ import annotations
from unittest.mock import AsyncMock
import asyncio

import pytest
from fastapi import HTTPException

from portal.routes import cms as cms_routes
from portal.backups import LANDING_CONTENT_DEFAULT


# ---------- in-memory fake Mongo ----------

class _SettingsColl:
    def __init__(self):
        self.docs = {}  # key -> stored value

    async def find_one(self, query):
        k = query.get("key")
        if k and k in self.docs:
            return {"key": k, "value": self.docs[k]}
        return None

    async def update_one(self, query, update, upsert=False):
        k = query["key"]
        self.docs[k] = update["$set"]["value"]


class _Db:
    def __init__(self):
        self.settings = _SettingsColl()


@pytest.fixture
def db(monkeypatch):
    value = _Db()
    monkeypatch.setattr(cms_routes, "_get_db", AsyncMock(return_value=value))
    return value


@pytest.fixture
def admin():
    return {"role": "admin", "email": "admin@example.test"}


# ---------- tests ----------


class TestLandingCMSImages:
    def test_public_get_includes_images_field(self, db):
        """GET returns 'images' key even when nothing stored (default {})."""
        result = asyncio.run(cms_routes.landing_content_get())
        assert "images" in result
        assert isinstance(result["images"], dict)

    def test_admin_post_images_and_persist(self, db, admin):
        """POST accepts 'images' and public GET reflects it."""
        payload = {
            "overrides": {},
            "faqs": [],
            "contact": {},
            "images": {
                "hero_main": {
                    "url": "/api/portal/media/file/507f1f77bcf86cd799439011",
                    "alt_id": "Server data center",
                    "alt_en": "Data center servers",
                },
                "infra_dc": {
                    "url": "https://images.unsplash.com/photo-example?w=800",
                    "alt_id": "Pusat data tier III",
                    "alt_en": "Tier III data center",
                },
            },
        }
        result = asyncio.run(cms_routes.landing_content_set(payload, admin=admin))
        assert "images" in result
        assert result["images"]["hero_main"]["url"] == payload["images"]["hero_main"]["url"]
        assert result["images"]["hero_main"]["alt_id"] == payload["images"]["hero_main"]["alt_id"]
        assert result["images"]["infra_dc"]["url"] == payload["images"]["infra_dc"]["url"]

        # Public GET must reflect
        result2 = asyncio.run(cms_routes.landing_content_get())
        assert result2["images"]["hero_main"]["url"] == payload["images"]["hero_main"]["url"]
        assert result2["images"]["infra_dc"]["alt_en"] == "Tier III data center"

    def test_admin_post_images_omitted_defaults_empty(self, db, admin):
        """Omitting 'images' entirely -> defaults to {}."""
        payload = {
            "overrides": {"hero.h1a": {"id": "Test", "en": "Test"}},
            "faqs": [],
            "contact": {},
        }
        result = asyncio.run(cms_routes.landing_content_set(payload, admin=admin))
        assert "images" in result
        assert result["images"] == {}

    def test_admin_post_partial_image_slot(self, db, admin):
        """Only url is required; alt text optional (defaults to '')."""
        payload = {
            "overrides": {},
            "faqs": [],
            "contact": {},
            "images": {
                "hero_main": {"url": "https://example.com/hero.jpg"},
            },
        }
        result = asyncio.run(cms_routes.landing_content_set(payload, admin=admin))
        assert result["images"]["hero_main"]["url"] == "https://example.com/hero.jpg"
        # alt fields are normalized to '' if missing
        assert result["images"]["hero_main"].get("alt_id", "") is not None
        assert result["images"]["hero_main"].get("alt_en", "") is not None

    def test_size_cap_with_images_413(self, db, admin):
        """128 KB cap applies to entire doc including images."""
        big_url = "https://example.com/" + "x" * 500
        images = {}
        for i in range(300):
            images[f"slot{i}"] = {"url": big_url, "alt_id": "x" * 50, "alt_en": "y" * 50}
        payload = {
            "overrides": {},
            "faqs": [],
            "contact": {},
            "images": images,
        }
        with pytest.raises(HTTPException) as exc:
            asyncio.run(cms_routes.landing_content_set(payload, admin=admin))
        assert exc.value.status_code == 413
        assert "128 KB" in str(exc.value.detail) or "cap" in str(exc.value.detail).lower()

    def test_admin_delete_wipes_images(self, db, admin):
        """DELETE resets images to {}."""
        # First set
        payload = {
            "overrides": {},
            "faqs": [],
            "contact": {},
            "images": {"hero_main": {"url": "test.jpg", "alt_id": "T", "alt_en": "T"}},
        }
        asyncio.run(cms_routes.landing_content_set(payload, admin=admin))

        # Delete
        result = asyncio.run(cms_routes.landing_content_reset(admin=admin))
        assert "images" in result
        assert result["images"] == {}

        # Public GET should reflect the reset
        result2 = asyncio.run(cms_routes.landing_content_get())
        assert result2["images"] == {}

    def test_default_shape_includes_images(self):
        """LANDING_CONTENT_DEFAULT includes empty images dict."""
        assert "images" in LANDING_CONTENT_DEFAULT
        assert LANDING_CONTENT_DEFAULT["images"] == {}
