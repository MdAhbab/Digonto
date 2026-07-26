"""Source discovery: the allowlist, and the crawl bounds.

Discovery is the one place where the open web reaches this product, so the tests
that matter are the negative ones. If an aggregator, a blog, or a consultancy's
marketing page can pass `is_official`, it can become a cited source, and "every
claim traces to an official source" stops being true. The bounds on link
expansion are tested for the same reason: an unbounded crawl on a single small VM
is a self-inflicted outage and a politeness failure toward government sites.
"""

from __future__ import annotations

import pytest

from app.workers.crawler import (
    MAX_CHILD_PAGES,
    discover_links,
    registrable_domain,
)
from app.workers.discovery import (
    MAX_REGISTERED_PER_QUERY,
    _extract_result_urls,
    build_query,
    is_official,
)

# --- the allowlist -----------------------------------------------------------

OFFICIAL = [
    "https://www.gov.uk/student-visa/money",
    "https://travel.state.gov/content/travel/en/us-visas/study/student-visa.html",
    "https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500",
    "https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada.html",
    "https://www.chevening.org/scholarship/bangladesh/",
    "https://cscuk.fcdo.gov.uk/scholarships/",
    "https://ugc.gov.bd/",
    "https://www.ox.ac.uk/admissions/graduate/fees-and-funding",
    "https://erasmus-plus.ec.europa.eu/opportunities/individuals/students",
    "https://www.studyinjapan.go.jp/en/",
    "https://ielts.org/take-a-test/test-types",
]

NOT_OFFICIAL = [
    "https://en.wikipedia.org/wiki/UK_student_visa",
    "https://www.quora.com/How-much-bank-balance-is-needed",
    "https://leverageedu.com/blog/uk-student-visa/",
    "https://medium.com/@someagent/uk-visa-tips",
    "https://www.shiksha.com/studyabroad/uk-student-visa",
    "https://collegedunia.com/uk",
    "https://best-consultancy.com.bd/uk-visa-guide",
    "https://www.reddit.com/r/ukvisa/comments/abc",
    "https://www.facebook.com/groups/ukstudents",
    "https://random-blog.net/visa",
]


@pytest.mark.parametrize("url", OFFICIAL)
def test_official_sources_are_admitted(url: str) -> None:
    assert is_official(url), url


@pytest.mark.parametrize("url", NOT_OFFICIAL)
def test_non_official_sources_are_rejected(url: str) -> None:
    assert not is_official(url), url


def test_blocklist_beats_a_matching_suffix() -> None:
    """A blocked host must stay blocked even on an otherwise admissible suffix."""
    assert not is_official("https://某.wikipedia.org/x")
    assert not is_official("https://en.m.wikipedia.org/wiki/Visa")


@pytest.mark.parametrize("url", ["", "not-a-url", "ftp://gov.uk/x", "javascript:alert(1)"])
def test_malformed_urls_are_rejected(url: str) -> None:
    assert not is_official(url)


def test_query_keeps_the_students_own_words() -> None:
    """The phrasing a student chose is the best signal available; don't discard it."""
    question = "যুক্তরাজ্যে পড়তে কত টাকা ব্যাংকে দেখাতে হবে?"
    query = build_query(question, country_name="United Kingdom")
    assert question in query
    assert "United Kingdom" in query
    assert len(query) <= 400


def test_query_without_a_country_still_builds() -> None:
    assert build_query("how much money", country_name=None).startswith("how much money")


def test_search_results_unwrap_the_redirector() -> None:
    html = (
        '<a href="/l/?kh=-1&amp;uddg=https%3A%2F%2Fwww.gov.uk%2Fstudent-visa%2Fmoney">Money</a>'
        '<a href="/l/?uddg=https%3A%2F%2Fquora.com%2Fx">Quora</a>'
    )
    urls = _extract_result_urls(html, limit=10)
    assert "https://www.gov.uk/student-visa/money" in urls
    assert [u for u in urls if is_official(u)] == ["https://www.gov.uk/student-visa/money"]


def test_search_results_skip_binaries() -> None:
    html = '<a href="https://www.gov.uk/a.pdf">PDF</a><a href="https://www.gov.uk/b">Page</a>'
    assert _extract_result_urls(html, limit=10) == ["https://www.gov.uk/b"]


def test_registration_per_query_is_capped() -> None:
    assert MAX_REGISTERED_PER_QUERY <= 5, "one question must not flood the crawl budget"


# --- same-site link expansion ------------------------------------------------


@pytest.mark.parametrize(
    "host,expected",
    [
        ("www.gov.uk", "gov.uk"),
        ("gov.uk", "gov.uk"),
        ("immi.homeaffairs.gov.au", "homeaffairs.gov.au"),
        ("travel.state.gov", "state.gov"),
        ("ugc.gov.bd", "ugc.gov.bd"),
        ("www.mofa.go.jp", "mofa.go.jp"),
        ("studyinnl.org", "studyinnl.org"),
    ],
)
def test_registrable_domain(host: str, expected: str) -> None:
    assert registrable_domain(host) == expected


def test_www_and_bare_domain_are_the_same_site() -> None:
    """Otherwise a site's links to its own bare domain look off-site and are skipped."""
    assert registrable_domain("www.gov.uk") == registrable_domain("gov.uk")


LINK_PAGE = """
<a href="/student-visa/money">Money you need</a>
<a href="/student-visa/documents">Documents you'll need</a>
<a href="/student-visa/knowledge-of-english">Knowledge of English</a>
<a href="/cookies">Cookies</a>
<a href="/accessibility-statement">Accessibility</a>
<a href="https://twitter.com/ukhomeoffice">Twitter</a>
<a href="/student-visa/money#top">Money (fragment duplicate)</a>
<a href="/guidance/fee-table.pdf">Fee table</a>
<a href="mailto:x@gov.uk">Email</a>
<a href="/student-visa">Self link</a>
"""


def test_expansion_keeps_only_relevant_same_site_pages() -> None:
    links = discover_links(LINK_PAGE, "https://www.gov.uk/student-visa")
    assert links == [
        "https://www.gov.uk/student-visa/money",
        "https://www.gov.uk/student-visa/documents",
        "https://www.gov.uk/student-visa/knowledge-of-english",
    ]


def test_expansion_excludes_offsite_binaries_and_chrome() -> None:
    links = discover_links(LINK_PAGE, "https://www.gov.uk/student-visa")
    joined = " ".join(links)
    for excluded in ("twitter.com", ".pdf", "mailto:", "/cookies", "accessibility"):
        assert excluded not in joined


def test_expansion_deduplicates_fragments_and_self_links() -> None:
    links = discover_links(LINK_PAGE, "https://www.gov.uk/student-visa")
    assert len(links) == len(set(links))
    assert "https://www.gov.uk/student-visa" not in links


def test_expansion_respects_the_page_cap() -> None:
    many = "".join(f'<a href="/visa-page-{i}">student visa {i}</a>' for i in range(200))
    assert len(discover_links(many, "https://www.gov.uk/x")) <= MAX_CHILD_PAGES


def test_expansion_survives_malformed_markup() -> None:
    assert isinstance(discover_links("<a href=", "https://www.gov.uk/x"), list)


def test_expansion_of_empty_html_is_empty() -> None:
    assert discover_links("", "https://www.gov.uk/x") == []


# --- precision rules found by crawling the real sites ------------------------


def test_child_must_live_under_the_parent_path() -> None:
    """Global navigation must not be mistaken for a section's own sub-pages.

    Crawling gov.uk/student-visa without this returned gov.uk/browse/tax, because
    the site-wide menu item "Money and tax" matched the "money" relevance hint.
    """
    html = (
        '<a href="/browse/tax">Money and tax</a>'
        '<a href="/browse/visas-immigration">Visas and immigration</a>'
        '<a href="/student-visa/money">Money you need</a>'
    )
    assert discover_links(html, "https://www.gov.uk/student-visa") == [
        "https://www.gov.uk/student-visa/money"
    ]


def test_site_root_portal_admits_any_path() -> None:
    """For a portal that *is* the site root, the whole site is the section."""
    html = '<a href="/finances">Financing your studies</a>'
    assert discover_links(html, "https://www.studyinnl.org/") == [
        "https://www.studyinnl.org/finances"
    ]


def test_print_views_are_skipped() -> None:
    """A print view is the same passages at a second URL, so it would double-store."""
    html = '<a href="/student-visa/print">Print this page</a><a href="/student-visa/apply">Apply</a>'
    links = discover_links(html, "https://www.gov.uk/student-visa")
    assert links == ["https://www.gov.uk/student-visa/apply"]


def test_query_string_variants_collapse_to_one_page() -> None:
    """gov.uk decorates its own nav with ?step-by-step-nav=<uuid>."""
    html = (
        '<a href="/student-visa/course">Course</a>'
        '<a href="/student-visa/course?step-by-step-nav=cafcc40a-c1ff-4997-adb4">Course</a>'
    )
    assert discover_links(html, "https://www.gov.uk/student-visa") == [
        "https://www.gov.uk/student-visa/course"
    ]


def test_links_inside_chrome_are_ignored() -> None:
    html = (
        "<nav><a href='/student-visa/money'>Money</a></nav>"
        "<footer><a href='/student-visa/fees'>Fees</a></footer>"
        "<main><a href='/student-visa/apply'>Apply for a student visa</a></main>"
    )
    assert discover_links(html, "https://www.gov.uk/student-visa") == [
        "https://www.gov.uk/student-visa/apply"
    ]
