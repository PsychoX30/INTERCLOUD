"""Contract test: publishing a CVE as an article must return a live URL.

Defect reproduced against production before this file existed.

`POST /admin/cve/{cve_id}/publish-article` answered with
`"url": f"/artikel/{slug}"`. No such route exists — `App.js` registers
`/articles/:slug`, the CMS sitemap emits `/articles/<slug>`, and nginx has no
`artikel` rule at all. The admin panel renders that value verbatim as the
"lihat artikel" link (`AdminCveTracker.jsx`), so the link always landed on the
React NotFound page even though the article published correctly at
`/articles/<slug>`.

That character is easy to miss and easy to reintroduce, so it is pinned here
from three directions: the literal route prefix, the fact that the slug is
interpolated (not hardcoded), and the absence of the dead prefix in live code.

Plain asserts, no pytest-asyncio: the prod venv has none.
"""
import inspect
import re

from portal.routes import cve as cve_route


def _live_source(fn) -> str:
    """Source of a function with comment lines stripped.

    The fix carries an explanatory comment that mentions the old `/artikel/`
    prefix. Checking raw source would therefore match the comment and report a
    false failure — only live code may be asserted on.
    """
    src = inspect.getsource(fn)
    return "\n".join(
        ln for ln in src.splitlines() if not ln.strip().startswith("#")
    )


def _url_expression(fn) -> str:
    live = _live_source(fn)
    for line in live.splitlines():
        if '"url"' in line:
            return line.strip()
    raise AssertionError("no 'url' key in the publish response")


# ------------------------------------------------------------- the defect
def test_url_uses_the_live_articles_route():
    """/articles/ is the registered route; /artikel/ is not."""
    line = _url_expression(cve_route.admin_cve_publish_article)
    assert "/articles/" in line, line


def test_url_does_not_use_the_dead_artikel_prefix():
    live = _live_source(cve_route.admin_cve_publish_article)
    assert "/artikel/" not in live, "the dead /artikel/ prefix is back in live code"


def test_url_still_interpolates_the_slug():
    """A hardcoded path would pass the prefix check but break every link."""
    line = _url_expression(cve_route.admin_cve_publish_article)
    assert "{slug}" in line, line


def test_url_is_a_root_relative_path():
    """The panel renders this as href; an absolute URL would pin the origin."""
    line = _url_expression(cve_route.admin_cve_publish_article)
    assert '"/articles/{slug}"' in line, line
    assert "http" not in line, line


# ------------------------------------------- shape of the publish response
def test_response_keys_are_stable():
    """The panel reads title, status, action, url and slug."""
    src = inspect.getsource(cve_route.admin_cve_publish_article)
    for key in ('"ok"', '"action"', '"article_id"', '"status"',
                '"title"', '"slug"', '"url"', '"cve_id"'):
        assert key in src, f"missing response key {key}"


# ------------------------------------------- cross-check other URL emitters
def test_sitemap_and_publish_agree_on_the_prefix():
    """The CMS sitemap and the publish response must emit the same prefix.

    These are two independent places that build an article URL. If they ever
    disagree, one of the two is handing out dead links.
    """
    from portal.routes import cms as cms_route

    cms_src = inspect.getsource(cms_route)
    publish = _url_expression(cve_route.admin_cve_publish_article)

    # The sitemap builds `<loc>{origin}/articles/{slug}</loc>`.
    assert re.search(r"/articles/\{slug\}", cms_src), \
        "sitemap no longer emits /articles/{slug}"
    assert "/articles/{slug}" in publish, publish
