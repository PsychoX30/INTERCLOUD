"""Articles / CMS — admin CRUD, tags, public listing, search, detail, SEO."""
import os
import uuid
import pytest
import requests

API = os.environ.get("PORTAL_API_BASE") or "http://localhost:8001/api/portal"


def _h(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={
        "email": os.environ["ADMIN_EMAIL"], "password": os.environ["ADMIN_PASSWORD"]})
    return r.json()["token"]


class TestPublicListing:
    def test_seed_articles_visible(self):
        r = requests.get(f"{API}/public/articles")
        assert r.status_code == 200
        d = r.json()
        assert d["total"] >= 3
        slugs = {a["slug"] for a in d["results"]}
        assert "colocation-vs-dedicated-vs-vps" in slugs

    def test_search_ranks_matching_result(self):
        r = requests.get(f"{API}/public/articles?q=colocation")
        assert r.status_code == 200
        d = r.json()
        assert d["total"] >= 1
        assert "colocation-vs-dedicated-vs-vps" in {a["slug"] for a in d["results"]}

    def test_tag_facet_returns_counts(self):
        r = requests.get(f"{API}/public/articles/tags")
        assert r.status_code == 200
        tags = {t["tag"] for t in r.json()}
        assert "colocation" in tags
        assert "cloud" in tags

    def test_filter_by_tag(self):
        r = requests.get(f"{API}/public/articles?tag=announcement")
        assert r.status_code == 200
        d = r.json()
        # Only the maintenance article should match
        assert d["total"] == 1
        assert d["results"][0]["slug"] == "cyber-1-core-network-upgrade-notice"


class TestPublicDetail:
    def test_detail_increments_view_count(self):
        slug = "why-indonesian-enterprises-move-local-cloud"
        r1 = requests.get(f"{API}/public/articles/{slug}")
        assert r1.status_code == 200
        v1 = r1.json()["article"]["view_count"]
        r2 = requests.get(f"{API}/public/articles/{slug}")
        v2 = r2.json()["article"]["view_count"]
        assert v2 == v1 + 1

    def test_detail_returns_related(self):
        r = requests.get(f"{API}/public/articles/why-indonesian-enterprises-move-local-cloud")
        assert r.status_code == 200
        d = r.json()
        # Not empty in the seeded set (they share no tags, but pipeline falls back to none)
        assert isinstance(d["related"], list)

    def test_detail_404_for_unknown_slug(self):
        r = requests.get(f"{API}/public/articles/does-not-exist-xyz")
        assert r.status_code == 404

    def test_draft_article_not_publicly_visible(self, admin_token):
        # Create a draft
        r = requests.post(f"{API}/admin/articles", headers=_h(admin_token), json={
            "title": "Draft never publish", "slug": "", "excerpt": "hidden",
            "body_html": "<p>secret</p>", "status": "draft", "tags": ["hidden"],
        })
        assert r.status_code == 200
        slug = r.json()["slug"]
        # Public GET must 404
        r2 = requests.get(f"{API}/public/articles/{slug}")
        assert r2.status_code == 404
        # Cleanup
        requests.delete(f"{API}/admin/articles/{r.json()['id']}", headers=_h(admin_token))


class TestAdminCRUD:
    def test_create_edit_delete_flow(self, admin_token):
        # CREATE
        title = f"Pytest article {uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/admin/articles", headers=_h(admin_token), json={
            "title": title, "slug": "", "excerpt": "test",
            "body_html": "<p>Body {content}</p>", "status": "draft",
            "tags": ["Pytest", "test", "  duplicate  ", "pytest"],
            "meta_title": "meta t", "meta_description": "meta d",
            "meta_keywords": ["kw1", "KW2"], "is_featured": False,
        })
        assert r.status_code == 200, r.text
        created = r.json()
        aid = created["id"]
        # tags normalised: lowercase, dedup, slug-friendly
        assert "pytest" in created["tags"]
        assert "test" in created["tags"]
        assert len(created["tags"]) == len(set(created["tags"]))
        assert created["slug"].startswith("pytest-article-")
        assert created["view_count"] == 0
        assert created["published_at"] in (None, "")

        # UPDATE — publish + change title
        new_title = title + " (edited)"
        r2 = requests.put(f"{API}/admin/articles/{aid}", headers=_h(admin_token), json={
            "title": new_title, "slug": created["slug"], "excerpt": "test",
            "body_html": "<p>New body</p>", "status": "published",
            "tags": created["tags"], "meta_title": "", "meta_description": "",
            "meta_keywords": [], "is_featured": True,
        })
        assert r2.status_code == 200
        upd = r2.json()
        assert upd["title"] == new_title
        assert upd["status"] == "published"
        assert upd["published_at"]     # auto-stamped
        assert upd["is_featured"] is True

        # PUBLIC — now visible
        r3 = requests.get(f"{API}/public/articles/{upd['slug']}")
        assert r3.status_code == 200

        # DELETE
        r4 = requests.delete(f"{API}/admin/articles/{aid}", headers=_h(admin_token))
        assert r4.status_code == 200
        assert r4.json()["deleted"] == 1

    def test_client_cannot_access_admin_articles(self, admin_token):
        client = requests.post(f"{API}/auth/login", json={
            "email": os.environ["CLIENT_EMAIL"], "password": os.environ["CLIENT_PASSWORD"]
        }).json()["token"]
        r = requests.get(f"{API}/admin/articles", headers=_h(client))
        assert r.status_code == 403
        r2 = requests.post(f"{API}/admin/articles", headers=_h(client), json={
            "title": "should be forbidden", "body_html": "<p>x</p>", "status": "draft",
        })
        assert r2.status_code == 403

    def test_slug_uniqueness_on_create(self, admin_token):
        base = f"pytest-slug-collision-{uuid.uuid4().hex[:6]}"
        r1 = requests.post(f"{API}/admin/articles", headers=_h(admin_token), json={
            "title": "First", "slug": base, "body_html": "<p>1</p>", "status": "draft",
        })
        r2 = requests.post(f"{API}/admin/articles", headers=_h(admin_token), json={
            "title": "Second", "slug": base, "body_html": "<p>2</p>", "status": "draft",
        })
        assert r1.status_code == 200 and r2.status_code == 200
        s1 = r1.json()["slug"]; s2 = r2.json()["slug"]
        assert s1 == base
        assert s2 == base + "-2"
        # Cleanup
        for a in (r1, r2):
            requests.delete(f"{API}/admin/articles/{a.json()['id']}", headers=_h(admin_token))

    def test_admin_search_and_status_filter(self, admin_token):
        r = requests.get(f"{API}/admin/articles?status=published", headers=_h(admin_token))
        assert r.status_code == 200
        for a in r.json():
            assert a["status"] == "published"
        r2 = requests.get(f"{API}/admin/articles?q=colocation", headers=_h(admin_token))
        assert r2.status_code == 200
        assert any(a["slug"] == "colocation-vs-dedicated-vs-vps" for a in r2.json())
