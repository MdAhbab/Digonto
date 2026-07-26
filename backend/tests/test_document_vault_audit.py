"""Tests for Prohori document auditing and content verification."""

from __future__ import annotations

from app.agents.prohori import _mechanical_findings


def test_research_paper_uploaded_as_passport_is_flagged() -> None:
    """When a research paper or non-passport document is uploaded under kind='passport',
    Prohori must flag it with INVALID_DOCUMENT_TYPE rather than reporting 'No issues found'.
    """
    docs = [
        {
            "id": 1,
            "kind": "passport",
            "expires_on": "2030-01-01",
            "fields": [
                {"field_key": "title", "value": "An Investigation of Machine Learning in Healthcare"},
                {"field_key": "author", "value": "John Doe"},
            ],
        },
        {
            "id": 2,
            "kind": "transcript",
            "expires_on": None,
            "fields": [
                {"field_key": "institution", "value": "University of Dhaka"},
                {"field_key": "cgpa", "value": "3.85"},
            ],
        },
        {
            "id": 3,
            "kind": "bank_statement",
            "expires_on": None,
            "fields": [
                {"field_key": "balance", "value": "4500000"},
                {"field_key": "currency", "value": "BDT"},
            ],
        },
    ]
    findings = _mechanical_findings(docs, profile=None, target=None)
    codes = {f["code"]: f for f in findings}

    assert "INVALID_DOCUMENT_TYPE" in codes
    assert codes["INVALID_DOCUMENT_TYPE"]["document_id"] == 1
    assert "not appear to be a valid passport" in codes["INVALID_DOCUMENT_TYPE"]["title_en"]
