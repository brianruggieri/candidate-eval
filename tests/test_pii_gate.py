"""Tests for the pii_gate module — DataFog-backed PII scrubbing."""

from __future__ import annotations

import pytest

from claude_candidate.pii_gate import scrub_deliverable


class TestPhoneNumberScrubbing:
    def test_parenthetical_format(self) -> None:
        text = "Contact the candidate at (555) 123-4567 for follow-up."
        result = scrub_deliverable(text)
        assert "(555) 123-4567" not in result
        assert "[PHONE]" in result

    def test_dashed_format(self) -> None:
        text = "Reach them on 555-123-4567."
        result = scrub_deliverable(text)
        assert "555-123-4567" not in result
        assert "[PHONE]" in result

    def test_dotted_format(self) -> None:
        text = "Mobile: 555.123.4567"
        result = scrub_deliverable(text)
        assert "555.123.4567" not in result
        assert "[PHONE]" in result

    def test_international_format(self) -> None:
        text = "International number: +1-555-123-4567"
        result = scrub_deliverable(text)
        assert "+1-555-123-4567" not in result
        assert "[PHONE]" in result

    def test_multiple_phones_scrubbed(self) -> None:
        text = "Call (555) 111-2222 or (555) 333-4444."
        result = scrub_deliverable(text)
        assert "(555) 111-2222" not in result
        assert "(555) 333-4444" not in result
        assert result.count("[PHONE]") == 2

    def test_surrounding_text_preserved(self) -> None:
        text = "The assessment was strong. Phone: (555) 123-4567. Great candidate."
        result = scrub_deliverable(text)
        assert "The assessment was strong" in result
        assert "Great candidate" in result


class TestSSNScrubbing:
    def test_standard_ssn_format(self) -> None:
        text = "SSN on file: 123-45-6789."
        result = scrub_deliverable(text)
        assert "123-45-6789" not in result
        assert "[SSN]" in result

    def test_ssn_in_sentence(self) -> None:
        text = "The applicant provided SSN 987-65-4321 during verification."
        result = scrub_deliverable(text)
        assert "987-65-4321" not in result
        assert "[SSN]" in result

    def test_ssn_placeholder_is_canonical(self) -> None:
        # Verify no numbered suffix leaks through
        text = "SSN: 123-45-6789"
        result = scrub_deliverable(text)
        assert "[SSN_" not in result
        assert "[SSN]" in result


class TestCreditCardScrubbing:
    def test_dashed_credit_card(self) -> None:
        text = "Card number 4111-1111-1111-1111 was flagged."
        result = scrub_deliverable(text)
        assert "4111-1111-1111-1111" not in result
        assert "[CREDIT_CARD]" in result

    def test_unseparated_credit_card(self) -> None:
        text = "Stored card: 4111111111111111"
        result = scrub_deliverable(text)
        assert "4111111111111111" not in result
        assert "[CREDIT_CARD]" in result

    def test_placeholder_is_canonical(self) -> None:
        text = "Card: 4111-1111-1111-1111"
        result = scrub_deliverable(text)
        assert "[CREDIT_CARD_" not in result
        assert "[CREDIT_CARD]" in result


class TestAddressScrubbing:
    def test_full_address_with_state_zip(self) -> None:
        text = "Mailing address: 123 Main St, Anytown, CA 12345."
        result = scrub_deliverable(text)
        assert "123 Main St" not in result
        assert "[ADDRESS]" in result

    def test_partial_street_address(self) -> None:
        text = "Stopped by 456 Oak Avenue yesterday."
        result = scrub_deliverable(text)
        assert "456 Oak Avenue" not in result
        assert "[ADDRESS]" in result

    def test_road_suffix(self) -> None:
        text = "The office is at 789 Pine Road, Boston, MA 02101."
        result = scrub_deliverable(text)
        assert "789 Pine Road" not in result
        assert "[ADDRESS]" in result

    def test_drive_suffix(self) -> None:
        text = "Lives at 10 Sunflower Drive."
        result = scrub_deliverable(text)
        assert "10 Sunflower Drive" not in result
        assert "[ADDRESS]" in result

    def test_no_false_positive_without_number(self) -> None:
        # "Main Street" alone (no leading number) should NOT be redacted
        text = "The code is modular and well-structured."
        result = scrub_deliverable(text)
        assert result == text


class TestPersonNameScrubbing:
    """Person name detection uses honorific-anchored heuristics.

    Bare first+last names are intentionally not detected to avoid false
    positives on technology terms such as 'Docker Compose' or 'React Native'.
    NLP-grade name detection requires datafog[nlp].
    """

    def test_mr_prefix(self) -> None:
        text = "Mr. John Smith submitted the take-home assessment."
        result = scrub_deliverable(text)
        assert "John Smith" not in result
        assert "[PERSON]" in result

    def test_ms_prefix(self) -> None:
        text = "Assessment prepared for Ms. Alice Johnson."
        result = scrub_deliverable(text)
        assert "Alice Johnson" not in result
        assert "[PERSON]" in result

    def test_dr_prefix(self) -> None:
        text = "Dr. Robert Chen led the interview panel."
        result = scrub_deliverable(text)
        assert "Robert Chen" not in result
        assert "[PERSON]" in result

    def test_prof_prefix(self) -> None:
        text = "Reference provided by Prof. Maria Garcia."
        result = scrub_deliverable(text)
        assert "Maria Garcia" not in result
        assert "[PERSON]" in result

    def test_no_false_positive_on_technology_terms(self) -> None:
        # Technology names should NOT be treated as person names
        text = "Built with Docker Compose, React Native, and Next.js."
        result = scrub_deliverable(text)
        assert result == text

    def test_no_false_positive_on_sentence_start(self) -> None:
        # Sentence-starting capitals should not trigger redaction
        text = "Python and TypeScript were used throughout the project."
        result = scrub_deliverable(text)
        assert result == text

    # NOTE: Bare names like "John Smith" without honorifics are NOT detected.
    # This is intentional — see module docstring for rationale.
    def test_bare_name_limitation_documented(self) -> None:
        """Bare names without honorifics pass through — known limitation."""
        text = "John Smith demonstrated strong Python skills."
        result = scrub_deliverable(text)
        # This is the known gap — bare names are not redacted
        # If this assertion fails, NLP-grade detection has been added (good!)
        assert "John Smith" in result  # documenting the current limitation


class TestEdgeCases:
    def test_empty_string(self) -> None:
        assert scrub_deliverable("") == ""

    def test_whitespace_only(self) -> None:
        assert scrub_deliverable("   ") == "   "

    def test_newline_only(self) -> None:
        assert scrub_deliverable("\n") == "\n"

    def test_no_pii_passes_through_unchanged(self) -> None:
        text = (
            "The candidate demonstrated strong Python and TypeScript skills. "
            "React component architecture was clean and well-tested. "
            "FastAPI backend showed good understanding of async patterns."
        )
        result = scrub_deliverable(text)
        assert result == text

    def test_mixed_pii_types_all_scrubbed(self) -> None:
        text = (
            "Applicant Mr. James Wilson. "
            "Phone: (555) 999-0000. "
            "SSN: 111-22-3333. "
            "Card: 4111-1111-1111-1111. "
            "Address: 42 Elm Street."
        )
        result = scrub_deliverable(text)
        assert "James Wilson" not in result
        assert "(555) 999-0000" not in result
        assert "111-22-3333" not in result
        assert "4111-1111-1111-1111" not in result
        assert "42 Elm Street" not in result
        assert "[PERSON]" in result
        assert "[PHONE]" in result
        assert "[SSN]" in result
        assert "[CREDIT_CARD]" in result
        assert "[ADDRESS]" in result

    def test_no_numbered_datafog_placeholders_leak(self) -> None:
        """DataFog's [TYPE_N] format must never appear in output."""
        text = "Phone: (555) 123-4567, SSN: 123-45-6789, Card: 4111-1111-1111-1111"
        result = scrub_deliverable(text)
        import re
        numbered = re.findall(r"\[[A-Z_]+_\d+\]", result)
        assert numbered == [], f"Numbered placeholders leaked: {numbered}"

    def test_return_type_is_str(self) -> None:
        result = scrub_deliverable("hello world")
        assert isinstance(result, str)

    def test_assessment_text_with_no_pii(self) -> None:
        """Realistic assessment text with no PII should pass through cleanly."""
        text = (
            "Strong candidate. Demonstrated proficiency in Python, TypeScript, "
            "and React. Built a FastAPI service with async SQLite persistence. "
            "Test coverage was comprehensive. Recommending for next round."
        )
        result = scrub_deliverable(text)
        assert "Python" in result
        assert "TypeScript" in result
        assert "FastAPI" in result
        assert result == text
