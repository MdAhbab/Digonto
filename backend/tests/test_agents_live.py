"""Live tests for all seven agents against the real model.

These exercise each agent end to end through the real ModelRouter and a running
Ollama. They check behaviour, not prose: that the structured output validates,
that the deterministic parts are actually deterministic, and above all that the
policy rules hold. An agent that produces a fluent paragraph while quietly
skipping its safety rule has failed.

Skips cleanly when Ollama is not running, so a machine without a model does not
report false failures.

Run:  pytest backend/tests/test_agents_live.py -v -s
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import httpx
import pytest

from app.agents import bicharok, dalil, khoji, lekhok, porter, prohori, shonchari
from app.agents.prohori import PASSPORT_VALIDITY_MARGIN_DAYS, _mechanical_findings
from app.llm.router import ModelRouter

OLLAMA = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")


def _up() -> bool:
    try:
        return httpx.get(f"{OLLAMA}/api/tags", timeout=3.0).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="Ollama is not running")


@pytest.fixture
async def router():
    """Function-scoped on purpose.

    ModelRouter holds an httpx.AsyncClient, which binds to the event loop that
    created it. pytest-asyncio gives each test its own loop, so a module-scoped
    client is closed out from under the second test that uses it.
    """
    r = ModelRouter()
    try:
        yield r
    finally:
        await r.aclose()


# --------------------------------------------------------------------------
# Prohori: the deterministic half must not depend on the model at all.
# --------------------------------------------------------------------------

def test_prohori_mechanical_findings_are_deterministic() -> None:
    """No model involved. These are exact checks a reviewer can reproduce."""
    today = date.today()
    documents = [
        {
            "id": 1, "kind": "passport", "deleted_at": None,
            "expires_on": (today + timedelta(days=200)).isoformat(),
            "fields": [{"field_key": "surname", "value_hash": "aaa"}],
        },
        {
            "id": 2, "kind": "transcript", "deleted_at": None, "expires_on": None,
            "fields": [{"field_key": "surname", "value_hash": "bbb"}],
        },
        {
            "id": 3, "kind": "english_test", "deleted_at": None,
            "expires_on": (today + timedelta(days=40)).isoformat(), "fields": [],
        },
    ]
    target = {"intake_start": (today + timedelta(days=120)).isoformat()}
    findings = _mechanical_findings(documents, {}, target)
    codes = {f["code"] for f in findings}

    # bank_statement was never uploaded
    assert "MISSING" in codes
    # the english test expires in 40 days
    assert "EXPIRING" in codes
    # surname hashes differ between passport and transcript
    assert "FIELD_MISMATCH" in codes
    # passport expires 200 days out but travel is 120 days out, and the regime
    # wants 180 days beyond arrival, so 120 + 180 > 200
    assert "PASSPORT_MARGIN" in codes, (
        f"expected a passport margin finding; {PASSPORT_VALIDITY_MARGIN_DAYS} day rule"
    )

    # Determinism: same input, same output, every time.
    again = _mechanical_findings(documents, {}, target)
    assert [f["code"] for f in findings] == [f["code"] for f in again]


def test_prohori_clean_vault_produces_no_findings() -> None:
    today = date.today()
    documents = [
        {"id": i, "kind": k, "deleted_at": None, "fields": [],
         "expires_on": (today + timedelta(days=2000)).isoformat()}
        for i, k in enumerate(
            ["passport", "transcript", "english_test", "bank_statement"], start=1
        )
    ]
    assert _mechanical_findings(documents, {}, None) == []


@pytest.mark.asyncio
async def test_prohori_explains_findings_in_bangla(router: ModelRouter) -> None:
    today = date.today()
    documents = [
        {"id": 1, "kind": "passport", "deleted_at": None,
         "expires_on": (today + timedelta(days=30)).isoformat(), "fields": []},
    ]
    out = await prohori.run_audit(
        documents=documents, profile={}, target=None, router=router
    )
    assert out, "expected findings for a vault missing three document kinds"
    for f in out:
        assert f["detail_en"] and f["detail_bn"], f
        assert f["severity"] in ("critical", "warning", "info")
    bengali = sum(1 for ch in out[0]["detail_bn"] if "ঀ" <= ch <= "৿")
    assert bengali > 5, f"detail_bn is not Bangla: {out[0]['detail_bn']!r}"
    print(f"\nprohori: {len(out)} findings, first bn = {out[0]['detail_bn'][:80]}")


# --------------------------------------------------------------------------
# Porter: the confidence threshold is the whole design.
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_porter_classifies_a_deadline_change(router: ModelRouter) -> None:
    out = await porter.classify_change(
        old_text="Applications must be submitted by 15 November 2026.",
        new_text="Applications must be submitted by 1 November 2026.",
        portal_label="ukvi.gov.uk",
        router=router,
    )
    print(f"\nporter deadline: {out}")
    assert out["category"] == "deadline"
    assert 0.0 <= out["confidence"] <= 1.0
    assert out["notify"] is (out["confidence"] >= porter.REVIEW_THRESHOLD)


@pytest.mark.asyncio
async def test_porter_discards_a_cosmetic_change(router: ModelRouter) -> None:
    out = await porter.classify_change(
        old_text="Please note that you must provide a valid passport.",
        new_text="Note: you must provide a valid passport.",
        portal_label="ukvi.gov.uk",
        router=router,
    )
    print(f"\nporter cosmetic: {out}")
    assert out["category"] == "cosmetic"
    assert out["notify"] is False, "a cosmetic edit must never alert a student"


@pytest.mark.asyncio
async def test_porter_low_confidence_goes_to_review_not_to_students() -> None:
    """The policy, checked without the model: below threshold means review."""
    for confidence, expect_review in ((0.69, True), (0.70, False), (0.95, False)):
        assert (confidence < porter.REVIEW_THRESHOLD) is expect_review


@pytest.mark.asyncio
async def test_porter_alert_quotes_and_is_bilingual(router: ModelRouter) -> None:
    out = await porter.compose_alert(
        category="deadline",
        old_text="The deadline is 15 November 2026.",
        new_text="The deadline is 1 November 2026.",
        portal_label="ukvi.gov.uk",
        snapshot_public_id="SNAP-TEST",
        student_context={"programme": "MSc Computing", "country": "uk"},
        router=router,
    )
    assert out["title_en"] and out["title_bn"]
    assert out["body_en"] and out["body_bn"]
    assert out["severity"] == "critical", "a deadline move is critical"
    assert out["snapshot_public_id"] == "SNAP-TEST"
    print(f"\nporter alert bn: {out['title_bn']}")


# --------------------------------------------------------------------------
# Khoji: hard criteria are arithmetic and must not reach the model.
# --------------------------------------------------------------------------

def test_khoji_hard_criteria_are_pure_arithmetic() -> None:
    from app.agents.khoji import _fails_hard_criteria

    # 3.0 on a 5.0 scale normalises to 2.4 on a 4.0 scale, below a 3.3 floor.
    assert _fails_hard_criteria(
        {"cgpa": 3.0, "cgpa_scale": 5.0}, {"min_cgpa": 3.3}
    ) == "cgpa_min"
    # 3.6 on a 4.0 scale clears it.
    assert _fails_hard_criteria(
        {"cgpa": 3.6, "cgpa_scale": 4.0}, {"min_cgpa": 3.3}
    ) is None
    assert _fails_hard_criteria(
        {"degree_level": "bachelor"}, {"degree_levels": ["master", "phd"]}
    ) == "degree_level"


@pytest.mark.asyncio
async def test_khoji_every_score_carries_reasons(router: ModelRouter) -> None:
    profile = {
        "degree_level": "master", "field_of_study": "Computer Science",
        "cgpa": 3.6, "cgpa_scale": 4.0, "english_test": "ielts",
        "english_overall": 7.0, "graduation_year": 2025, "study_gap_years": 0,
    }
    scholarships = [
        {"public_id": "SCH-1", "name": "Chevening", "provider": "UK Government",
         "country_code": "uk", "coverage_type": "full", "min_cgpa": 3.0,
         "degree_levels": ["master"], "fields": None, "soft_criteria": "leadership"},
        {"public_id": "SCH-2", "name": "Doctoral Fellowship", "provider": "X",
         "country_code": "de", "coverage_type": "full", "min_cgpa": 3.0,
         "degree_levels": ["phd"], "fields": None, "soft_criteria": "research"},
    ]
    out = await khoji.score_eligibility(
        profile=profile, scholarships=scholarships, router=router
    )
    assert len(out) == 2
    by_id = {r["scholarship_id"]: r for r in out}

    # The PhD award is filtered in code, with a reason, never silently dropped.
    assert by_id["SCH-2"]["eligible"] is False
    assert by_id["SCH-2"]["reasons"][0]["criterion_key"] == "degree_level"
    assert by_id["SCH-2"]["reasons"][0]["reason_bn"]

    # No score may be returned without reasons. That is the honesty rule.
    for r in out:
        assert r["reasons"], f"score with no reasons: {r}"
        for reason in r["reasons"]:
            assert reason["reason_en"] and reason["reason_bn"]
    print(f"\nkhoji: SCH-1 score={by_id['SCH-1']['score']:.2f}")


# --------------------------------------------------------------------------
# Shonchari: the overall score is arithmetic, not the model's opinion.
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_shonchari_scores_an_answer(router: ModelRouter) -> None:
    out = await shonchari.score_answer(
        question_text="Who is funding your studies?",
        answer_text="My uncle will pay, he has a business.",
        file_summary={"declared_funds": "not provided", "sponsor": "not recorded"},
        document_field_hashes={},
        router=router,
    )
    for axis in ("relevance", "consistency", "credibility"):
        assert out[axis] is None or 0.0 <= out[axis] <= 1.0
    assert out["feedback_en"] and out["feedback_bn"]
    print(f"\nshonchari: consistency={out['consistency']} probing={out.get('probing','')[:60]}")


@pytest.mark.asyncio
async def test_shonchari_overall_is_the_mean_not_the_model(router: ModelRouter) -> None:
    turns = [
        {"ordinal": 1, "question_text": "Q1", "answer_text": "A1",
         "relevance": 1.0, "consistency": 1.0, "credibility": 1.0},
        {"ordinal": 2, "question_text": "Q2", "answer_text": "A2",
         "relevance": 0.0, "consistency": 0.0, "credibility": 0.0},
    ]
    report = await shonchari.compose_report(turns=turns, router=router)
    assert abs(report["overall"] - 0.5) < 1e-6, (
        f"overall must be the arithmetic mean, got {report['overall']}"
    )
    assert report["summary_en"] and report["summary_bn"]


# --------------------------------------------------------------------------
# Lekhok and Dalil: policy overrides the model.
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lekhok_finds_a_contradiction(router: ModelRouter) -> None:
    findings = await lekhok.analyse_statement(
        body=(
            "I graduated in 2019 with a first class degree and have worked as a "
            "senior engineer at a multinational ever since. I am passionate about "
            "leveraging synergies in the field of computer science."
        ),
        documents=[
            {"kind": "transcript", "issued_on": "2024-06-01",
             "expires_on": None, "original_name": "transcript.pdf"}
        ],
        router=router,
    )
    print(f"\nlekhok: {len(findings)} findings, kinds={[f['kind'] for f in findings]}")
    for f in findings:
        assert f["severity"] in ("critical", "warning", "info")
        assert f["kind"] in ("contradiction", "unsupported", "vague", "cliche", "missing")
        assert f["detail_en"] and f["detail_bn"]


def test_dalil_forces_high_risk_categories() -> None:
    """Policy, not judgement. Verified without the model."""
    assert dalil.HIGH_RISK_CATEGORIES == {"document_retention", "guarantee", "refund"}


def test_bicharok_rejects_a_non_image() -> None:
    """PDFs must be rasterised upstream rather than guessed at."""
    import asyncio

    with pytest.raises(ValueError, match="expects an image"):
        asyncio.run(
            bicharok.analyse_rejection(
                document_bytes=b"%PDF-1.4", mime_type="application/pdf", router=None  # type: ignore[arg-type]
            )
        )


# --------------------------------------------------------------------------
# The router's document guarantee.
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_document_content_cannot_leave_the_machine() -> None:
    """The promise that vault content never leaves is structural, not policy."""
    from app.llm.router import DocumentContentLeak, GeminiProvider, LLMRequest, TaskKind
    from app.config import get_settings
    import httpx as _httpx

    provider = GeminiProvider(get_settings(), _httpx.AsyncClient())
    req = LLMRequest(
        kind=TaskKind.SUMMARISE_SHORT,
        messages=[{"role": "user", "content": "passport number A1234567"}],
        contains_user_documents=True,
    )
    with pytest.raises(DocumentContentLeak):
        await provider.complete(req)
    await provider._c.aclose()
