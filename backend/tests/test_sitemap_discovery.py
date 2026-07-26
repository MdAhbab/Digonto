"""Reading a site's own sitemap, and refusing to let it widen the crawl.

Link scraping finds what a page chooses to link, which is the better first source
because a link is the site asserting that one page leads to another. It also misses
pages behind a "show all" control that needs JavaScript, and on a government site
those are often the pages carrying the figures a student needs.

A sitemap fixes the coverage gap and introduces a risk: it lists everything. So the
question these tests answer is not "does it find more pages" but "does a URL from a
sitemap have to clear exactly the same bounds as one from an anchor".
"""

from __future__ import annotations

import httpx
import pytest

from app.workers.crawler import (
    MAX_CHILD_PAGES,
    _acceptable_child,
    _robots,
    discover_from_sitemap,
    parse_sitemap_locs,
)

SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.gov.uk/student-visa/money</loc></url>
  <url><loc>https://www.gov.uk/student-visa/documents-you-must-provide</loc></url>
  <url><loc>https://www.gov.uk/student-visa/knowledge-of-english</loc></url>
  <url><loc>https://www.gov.uk/browse/tax/income-tax</loc></url>
  <url><loc>https://www.gov.uk/student-visa/print</loc></url>
  <url><loc>https://www.gov.uk/student-visa/guidance.pdf</loc></url>
  <url><loc>https://not-gov-uk.example/student-visa/money</loc></url>
  <url><loc>https://www.gov.uk/student-visa</loc></url>
  <url><loc>https://www.gov.uk/student-visa/cookies</loc></url>
</urlset>
"""

SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.gov.uk/sitemaps/student-visa.xml</loc></sitemap>
  <sitemap><loc>https://www.gov.uk/sitemaps/corporate-reports.xml</loc></sitemap>
</sitemapindex>
"""


@pytest.fixture(autouse=True)
def _clear_robots_cache():
    """The robots cache is module-level, so a stale host entry would leak between tests."""
    _robots._parsers.clear()
    _robots._locks.clear()
    yield
    _robots._parsers.clear()
    _robots._locks.clear()


def _serve(routes: dict[str, tuple[int, str]]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        status, body = routes.get(str(request.url), (404, "not found"))
        return httpx.Response(status, text=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- Parsing -----------------------------------------------------------------


def test_parse_reads_locs_and_distinguishes_an_index():
    locs, is_index = parse_sitemap_locs(SITEMAP)
    assert "https://www.gov.uk/student-visa/money" in locs
    assert is_index is False

    locs, is_index = parse_sitemap_locs(SITEMAP_INDEX)
    assert is_index is True
    assert len(locs) == 2


def test_parse_survives_the_input_being_hostile_or_not_xml_at_all():
    """This is third-party input, so it must not be able to raise.

    A regular expression is used rather than a stdlib XML parser precisely because
    the stdlib parsers are documented as unsafe on untrusted data. An entity-
    expansion payload here is inert text.
    """
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE t [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        "<urlset><url><loc>&b;</loc></url></urlset>"
    )
    locs, _ = parse_sitemap_locs(bomb)
    assert locs == ["&b;"]  # read as text, never expanded

    assert parse_sitemap_locs("") == ([], False)
    assert parse_sitemap_locs("<html>404 Not Found</html>") == ([], False)
    assert parse_sitemap_locs("<urlset><url><loc></loc></url></urlset>") == ([], False)


def test_parse_respects_the_loc_limit():
    many = "<urlset>" + "".join(
        f"<url><loc>https://x.gov/{i}</loc></url>" for i in range(50)
    ) + "</urlset>"
    locs, _ = parse_sitemap_locs(many, limit=10)
    assert len(locs) == 10


# --- The shared gate ---------------------------------------------------------


def test_the_gate_is_the_same_one_link_scraping_uses():
    kw = {"base_domain": "gov.uk", "base_prefix": "/student-visa"}

    assert _acceptable_child("https://www.gov.uk/student-visa/money", **kw)
    # www is stripped before comparison, so a site's links to its own bare domain
    # are not treated as off-site.
    assert _acceptable_child("https://gov.uk/student-visa/money", **kw)

    assert _acceptable_child("https://www.gov.uk/browse/tax", **kw) is None
    assert _acceptable_child("https://elsewhere.example/student-visa/money", **kw) is None
    assert _acceptable_child("https://www.gov.uk/student-visa/x.pdf", **kw) is None
    assert _acceptable_child("https://www.gov.uk/student-visa/print", **kw) is None
    assert _acceptable_child("ftp://www.gov.uk/student-visa/money", **kw) is None


def test_the_gate_strips_query_and_fragment():
    clean = _acceptable_child(
        "https://www.gov.uk/student-visa/money?step-by-step-nav=abc#top",
        base_domain="gov.uk",
        base_prefix="/student-visa",
    )
    assert clean == "https://www.gov.uk/student-visa/money"


# --- Discovery ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_sitemap_urls_must_clear_every_bound_link_scraping_clears():
    routes = {
        "https://www.gov.uk/robots.txt": (
            200,
            "User-agent: *\nAllow: /\nSitemap: https://www.gov.uk/sitemap.xml\n",
        ),
        "https://www.gov.uk/sitemap.xml": (200, SITEMAP),
    }
    async with _serve(routes) as client:
        found = await discover_from_sitemap(
            client, "https://www.gov.uk/student-visa", limit=MAX_CHILD_PAGES
        )

    assert found == [
        "https://www.gov.uk/student-visa/money",
        "https://www.gov.uk/student-visa/documents-you-must-provide",
        "https://www.gov.uk/student-visa/knowledge-of-english",
    ]
    # Everything excluded, and the reason for each:
    #   /browse/tax          off-section (the bug link scraping had)
    #   not-gov-uk.example   off-site
    #   /print               duplicate rendering of a page already held
    #   guidance.pdf         not a passage source
    #   /student-visa        the parent itself
    #   /student-visa/cookies   no relevance hint below the parent's own path
    assert not any("browse/tax" in u for u in found)
    assert not any("not-gov-uk" in u for u in found)
    assert not any(u.endswith("/print") for u in found)
    assert not any(u.endswith("/cookies") for u in found)


def test_hints_are_matched_below_the_parent_path_not_across_the_whole_path():
    """The bug this closes made the relevance filter admit everything.

    Every child of `/student-visa` contains "visa" and "stud" in its path, because
    the parent's path is a prefix of the child's. So a cookie page inside the
    section passed the hint test, and the path-prefix rule was silently carrying all
    of the precision on its own.
    """
    from app.workers.crawler import _RELEVANT_HINTS, _below_prefix

    def relevant(path: str, prefix: str) -> bool:
        return any(h in _below_prefix(path, prefix) for h in _RELEVANT_HINTS)

    assert relevant("/student-visa/money", "/student-visa")
    assert relevant("/student-visa/documents-you-must-provide", "/student-visa")
    assert not relevant("/student-visa/cookies", "/student-visa")
    assert not relevant("/student-visa/accessibility", "/student-visa")
    assert not relevant("/study-permit/privacy", "/study-permit")

    # A site-root portal has no prefix to remove, so the whole path is the evidence.
    assert relevant("/finances", "")
    assert _below_prefix("/student-visa/Money", "/student-visa") == "/money"


@pytest.mark.asyncio
async def test_no_sitemap_declared_is_the_normal_case_and_returns_nothing():
    routes = {"https://example.gov/robots.txt": (200, "User-agent: *\nAllow: /\n")}
    async with _serve(routes) as client:
        assert await discover_from_sitemap(client, "https://example.gov/visa", limit=8) == []


@pytest.mark.asyncio
async def test_a_missing_robots_txt_does_not_raise():
    async with _serve({}) as client:
        assert await discover_from_sitemap(client, "https://example.gov/visa", limit=8) == []


@pytest.mark.asyncio
async def test_a_site_root_portal_is_skipped_because_there_is_no_section_to_bound():
    """With no path prefix, a sitemap would offer the entire site.

    The relevance hints alone are not a strong enough bound for that, so for a
    portal like studyinnl.org sitemap reading declines and link scraping stands on
    its own. Returning nothing here is the intended answer, not a gap.
    """
    routes = {
        "https://www.studyinnl.org/robots.txt": (
            200, "User-agent: *\nSitemap: https://www.studyinnl.org/sitemap.xml\n"
        ),
        "https://www.studyinnl.org/sitemap.xml": (
            200,
            "<urlset><url><loc>https://www.studyinnl.org/finances</loc></url></urlset>",
        ),
    }
    async with _serve(routes) as client:
        assert await discover_from_sitemap(client, "https://www.studyinnl.org/", limit=8) == []


@pytest.mark.asyncio
async def test_an_index_is_followed_one_level_and_only_into_this_section():
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        fetched.append(url)
        if url.endswith("/robots.txt"):
            return httpx.Response(
                200, text="User-agent: *\nSitemap: https://www.gov.uk/sitemap.xml\n"
            )
        if url == "https://www.gov.uk/sitemap.xml":
            return httpx.Response(200, text=SITEMAP_INDEX)
        if url == "https://www.gov.uk/sitemaps/student-visa.xml":
            return httpx.Response(200, text=SITEMAP)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        found = await discover_from_sitemap(
            client, "https://www.gov.uk/student-visa", limit=MAX_CHILD_PAGES
        )

    assert "https://www.gov.uk/student-visa/money" in found
    # The unrelated child of the index was never opened: three fetches would be
    # spent on a site-wide index otherwise.
    assert "https://www.gov.uk/sitemaps/corporate-reports.xml" not in fetched


@pytest.mark.asyncio
async def test_the_limit_is_respected_so_the_child_budget_cannot_be_exceeded():
    routes = {
        "https://www.gov.uk/robots.txt": (
            200, "User-agent: *\nSitemap: https://www.gov.uk/sitemap.xml\n"
        ),
        "https://www.gov.uk/sitemap.xml": (200, SITEMAP),
    }
    async with _serve(routes) as client:
        found = await discover_from_sitemap(
            client, "https://www.gov.uk/student-visa", limit=1
        )
    assert len(found) == 1


@pytest.mark.asyncio
async def test_a_zero_or_negative_budget_makes_no_requests_at_all():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, text="User-agent: *\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await discover_from_sitemap(client, "https://x.gov/visa", limit=0) == []
    assert calls["n"] == 0


@pytest.mark.asyncio
async def test_a_sitemap_on_another_domain_is_not_fetched():
    """robots.txt may declare any URL, including one the site does not control."""
    fetched: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        fetched.append(str(request.url))
        if str(request.url).endswith("/robots.txt"):
            return httpx.Response(
                200, text="User-agent: *\nSitemap: https://cdn.elsewhere.example/s.xml\n"
            )
        return httpx.Response(200, text=SITEMAP)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        found = await discover_from_sitemap(client, "https://www.gov.uk/student-visa", limit=8)

    assert found == []
    assert not any("elsewhere.example" in u for u in fetched)


@pytest.mark.asyncio
async def test_robots_txt_is_fetched_once_per_host_not_once_per_portal():
    """Three portals share gov.uk; twenty share a cron. This is the cost of that."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/robots.txt"):
            calls["n"] += 1
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for path in ("/student-visa", "/student-visa/money", "/skilled-worker-visa"):
            await _robots.allowed(client, f"https://www.gov.uk{path}")

    assert calls["n"] == 1
