"""Passage extraction, and the chrome that must never become a citation.

A live crawl of gov.uk showed the first passage extracted from every page was
"We use some essential cookies to make this website work." A cookie banner is a
`<p>` inside `<body>`, so it was embedded and retrievable, which means a student
could in principle be shown a citation to a cookie notice as evidence about their
visa requirements. Stripping only `script, style, nav` was not enough.

These tests use fixture HTML shaped like the real pages rather than hitting the
network, so they run in CI and pin the behaviour rather than the sites.
"""

from __future__ import annotations

from app.workers.crawler import (
    MIN_PASSAGE_CHARS,
    normalise_and_extract,
    sha256_hex,
)

GOVUK_SHAPED = """
<html><body>
  <div id="global-cookie-message" class="gem-c-cookie-banner">
    <p>We use some essential cookies to make this website work.</p>
    <button>Accept additional cookies</button>
  </div>
  <header role="banner"><a href="/">GOV.UK</a></header>
  <nav class="gem-c-breadcrumbs"><a href="/browse/visas">Visas and immigration</a></nav>
  <main>
    <h1>Student visa</h1>
    <h2>Overview</h2>
    <p>You can apply for a Student visa to study in the UK if you are 16 or over.</p>
    <h2>Money you need</h2>
    <h3>Course fees</h3>
    <p>You need enough money to pay for your course for one academic year.</p>
    <ul><li>Short</li><li>You must have GBP 1,483 per month for up to 9 months in London.</li></ul>
  </main>
  <footer><p>All content is available under the Open Government Licence v3.0.</p></footer>
</body></html>
"""


def _texts(html: str) -> list[str]:
    _normalised, passages = normalise_and_extract(html)
    return [p["text"] for p in passages]


def test_cookie_banner_is_not_a_passage() -> None:
    joined = " ".join(_texts(GOVUK_SHAPED)).lower()
    assert "essential cookies" not in joined
    assert "accept additional cookies" not in joined


def test_header_nav_and_footer_are_not_passages() -> None:
    joined = " ".join(_texts(GOVUK_SHAPED)).lower()
    for chrome in ("gov.uk", "visas and immigration", "open government licence"):
        assert chrome not in joined, chrome


def test_real_content_survives() -> None:
    joined = " ".join(_texts(GOVUK_SHAPED))
    assert "16 or over" in joined
    assert "one academic year" in joined
    assert "1,483 per month" in joined


def test_short_fragments_are_dropped() -> None:
    """A bare list label is not a statement a citation can rest on."""
    assert "Short" not in _texts(GOVUK_SHAPED)
    assert all(len(t) >= MIN_PASSAGE_CHARS for t in _texts(GOVUK_SHAPED))


def test_section_path_is_the_heading_breadcrumb() -> None:
    """This is what lets a citation read "Money you need > Course fees"."""
    _n, passages = normalise_and_extract(GOVUK_SHAPED)
    by_text = {p["text"][:30]: p["section_path"] for p in passages}
    fees = next(v for k, v in by_text.items() if "academic year" in k or "enough money" in k)
    assert fees is not None
    assert "Money you need" in fees and "Course fees" in fees


def test_heading_stack_pops_correctly() -> None:
    """An h2 after an h3 must not leave the h3 in the breadcrumb."""
    html = """<html><body>
      <h2>First</h2><h3>Nested</h3>
      <p>This paragraph sits under First then Nested, which is long enough.</p>
      <h2>Second</h2>
      <p>This paragraph sits only under Second, and is also long enough here.</p>
    </body></html>"""
    _n, passages = normalise_and_extract(html)
    paths = [p["section_path"] for p in passages]
    assert paths[0] == "First > Nested"
    assert paths[1] == "Second", "the h3 must have been popped"


def test_hash_is_stable_and_content_sensitive() -> None:
    a, _ = normalise_and_extract(GOVUK_SHAPED)
    b, _ = normalise_and_extract(GOVUK_SHAPED)
    assert sha256_hex(a) == sha256_hex(b), "an unchanged page must hash the same"

    changed = GOVUK_SHAPED.replace("1,483", "1,510")
    c, _ = normalise_and_extract(changed)
    assert sha256_hex(a) != sha256_hex(c), "a changed amount must change the hash"


def test_chrome_only_change_does_not_change_the_hash() -> None:
    """The cheap path: a reworded cookie banner must not look like a policy change.

    This is the property that makes polling dozens of portals affordable. Before
    chrome was stripped, a site rotating its banner text would have produced a
    content change, a snapshot write, a diff, an embed, and a Porter classification
    on every crawl.
    """
    a, _ = normalise_and_extract(GOVUK_SHAPED)
    b, _ = normalise_and_extract(
        GOVUK_SHAPED.replace(
            "We use some essential cookies to make this website work.",
            "This site uses cookies. Manage your preferences at any time.",
        )
    )
    assert sha256_hex(a) == sha256_hex(b)


def test_bangla_content_is_detected_and_kept() -> None:
    html = (
        "<html><body><h2>তথ্য</h2><p>"
        "যুক্তরাজ্যে পড়তে আপনাকে ব্যাংকে নির্দিষ্ট পরিমাণ টাকা দেখাতে হবে।"
        "</p></body></html>"
    )
    _n, passages = normalise_and_extract(html)
    assert len(passages) == 1
    assert passages[0]["lang"] == "bn"


def test_empty_and_bodyless_html_do_not_raise() -> None:
    for html in ("", "<html></html>", "<p>fragment with no body element at all here</p>"):
        normalised, passages = normalise_and_extract(html)
        assert isinstance(normalised, str) and isinstance(passages, list)
