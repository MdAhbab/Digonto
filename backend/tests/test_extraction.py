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


# --- Content region, and repeats within one page -----------------------------


def test_the_content_region_is_preferred_over_the_whole_body() -> None:
    """Stripping chrome removes what is recognisably chrome.

    A page also carries parts that are neither chrome nor content: a related-links
    rail, a feedback panel, a "last updated" block. Those use none of the
    conventions _STRIP_SELECTOR knows, so they survived the strip and became
    passages. Selecting the content region positively excludes them.
    """
    html = """
    <html><body>
      <div class="related-items">
        <p>Related content: Skilled Worker visa, Graduate visa, Visitor visa guidance.</p>
      </div>
      <main>
        <h1>Student visa</h1>
        <p>You must have enough money to pay your course fees for one academic year.</p>
        <p>You must also have enough money to support yourself while you are studying,
           and the amount depends on whether your course is inside or outside London.</p>
        <p>You will usually need to prove you have held the money for 28 consecutive days
           ending no more than 31 days before you apply.</p>
      </main>
      <div class="feedback">
        <p>Is this page useful? Report a problem with this page and we will fix it.</p>
      </div>
    </body></html>
    """
    texts = _texts(html)
    assert any("course fees" in t for t in texts)
    assert not any("Related content" in t for t in texts)
    assert not any("Is this page useful" in t for t in texts)


def test_a_decorative_main_does_not_reduce_the_page_to_nothing() -> None:
    """A site that wraps a sidebar in <main> must not cost us the page.

    The floor means the body is used instead, which is the previous behaviour and
    is never worse than returning nothing.
    """
    html = """
    <html><body>
      <main><p>Menu</p></main>
      <div id="page">
        <h1>Student visa</h1>
        <p>You need to show 1,483 pounds per month for up to nine months in London.</p>
        <p>You must also pay the immigration health surcharge before you travel.</p>
      </div>
    </body></html>
    """
    texts = _texts(html)
    assert any("1,483 pounds" in t for t in texts)


def test_text_repeated_across_a_page_becomes_one_passage() -> None:
    """Government pages repeat a standing sentence in several sections.

    Each copy used to be embedded, stored and retrieved separately, so one fact
    could occupy several of the shortlist slots a grounded answer chooses from.
    """
    standing = (
        "You must show you have enough money to support yourself for the whole course."
    )
    html = f"""
    <html><body><main>
      <h2>Money</h2><p>{standing}</p>
      <h2>Documents</h2><p>{standing}</p>
      <h2>Applying</h2><p>{standing}</p>
      <p>Fees are set by your university and are not refundable after enrolment.</p>
    </main></body></html>
    """
    _n, passages = normalise_and_extract(html)
    texts = [p["text"] for p in passages]
    assert texts.count(standing) == 1
    assert len(passages) == 2
    # Ordinals stay dense and start at zero: `passages` is UNIQUE (snapshot_id,
    # ordinal), and a gap would make the diff between two snapshots read as a move.
    assert [p["ordinal"] for p in passages] == [0, 1]
    # The kept copy is the first, so its section_path is the section it first
    # appeared under rather than an arbitrary later one.
    assert passages[0]["section_path"] == "Money"


def test_deduplication_is_by_exact_text_not_by_similarity() -> None:
    """Two passages that differ by a number are two different facts."""
    html = """
    <html><body><main>
      <p>You need 1,483 pounds per month for up to nine months if you study in London.</p>
      <p>You need 1,136 pounds per month for up to nine months if you study elsewhere.</p>
    </main></body></html>
    """
    assert len(_texts(html)) == 2


def test_screen_reader_only_text_does_not_double_a_section_path() -> None:
    """From a live crawl of study-in-germany.de.

    The heading is `<span class="sr-only">Step 1: Determine the type of
    Stay</span>Determine the type of Stay`, and deep text extraction concatenated
    both copies, so every citation under it read "Step 1: Determine the type of Stay
    Determine the type of Stay". The visible copy is the one kept, because a citation
    should read the way the page reads when a student opens it.
    """
    html = """
    <html><body><main>
      <h2 class="chapter-headline__text">
        <span class="sr-only">Step 1: Determine the type of Stay</span>
        Determine the type of Stay
      </h2>
      <p>Are you planning to come to Germany before, during or after your studies?</p>
    </main></body></html>
    """
    _n, passages = normalise_and_extract(html)
    assert passages[0]["section_path"] == "Determine the type of Stay"


def test_the_other_hidden_text_conventions_are_stripped_too() -> None:
    """gov.uk uses govuk-visually-hidden at scale for link and skip-link annotations."""
    html = """
    <html><body><main>
      <h2>Money you need<span class="govuk-visually-hidden"> (opens in a new tab)</span></h2>
      <p>You must have 1,483 pounds per month for up to nine months to study in London.</p>
      <p aria-hidden="true">Decorative duplicate of the sentence above for layout only.</p>
      <p class="screen-reader-text">Announcement read only to assistive technology users.</p>
    </main></body></html>
    """
    _n, passages = normalise_and_extract(html)
    assert passages[0]["section_path"] == "Money you need"
    assert len(passages) == 1


# --- retrieval degradation ---------------------------------------------------


def test_lexical_fallback_exists_and_search_reports_when_it_was_used() -> None:
    """The vector store was a single point of failure for the whole product.

    `dense()` returned [] when no collection was live, `search()` returned nothing, and
    the pipeline refused. Each step was correct and the composition answered nothing at
    all, including for questions whose answer was in the same database as the question.
    """
    import inspect

    from app.rag.retrieval import Retriever

    assert hasattr(Retriever, "lexical_only")
    src = inspect.getsource(Retriever.search)
    # The contract is `(passages, degraded)`, so a caller cannot use the result without
    # deciding what to do about the degradation.
    assert "return fallback, True" in src
    assert "return ranked[: self._s.retrieval_rerank_to], False" in src
    # An embedding failure must not be fatal when a working lexical path exists.
    assert "except Exception" in src and "falling back to lexical" in src
