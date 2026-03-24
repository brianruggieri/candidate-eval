"""
PII Gate: NER-detectable PII scrubber for deliverable text.

This module is the second layer of the privacy trust boundary, complementing
sanitizer.py. While sanitizer.py handles structured secrets (API keys, auth
tokens, emails, absolute paths via regex), this module targets NER-detectable
PII that would appear in generated assessment text: person names, phone
numbers, physical addresses, SSNs, and credit card numbers.

No deliverable ships to a hiring manager until scrub_deliverable() has run.

Coverage overview
-----------------
Category        | Detection method       | Placeholder
--------------- | ---------------------- | -----------
Phone numbers   | DataFog regex          | [PHONE]
SSNs            | DataFog regex          | [SSN]
Credit cards    | DataFog regex          | [CREDIT_CARD]
Email addresses | DataFog regex          | [EMAIL]
Physical addrs  | Supplemental regex     | [ADDRESS]
Person names    | Supplemental regex *   | [PERSON]

* Name detection uses an honorific-anchored heuristic. It catches names
  introduced by Mr./Mrs./Ms./Dr./Prof. but is intentionally conservative to
  avoid false positives on technology terms (e.g. "Python", "Docker Compose").
  For NLP-grade name detection, install datafog[nlp] and update this module
  to use SpacyPIIAnnotator. This limitation is documented here and in the
  test suite.
"""

from __future__ import annotations

import re

from datafog import DataFog

# ---------------------------------------------------------------------------
# Category-specific placeholders
# ---------------------------------------------------------------------------

_PLACEHOLDER_PHONE = "[PHONE]"
_PLACEHOLDER_SSN = "[SSN]"
_PLACEHOLDER_CREDIT_CARD = "[CREDIT_CARD]"
_PLACEHOLDER_EMAIL = "[EMAIL]"
_PLACEHOLDER_ADDRESS = "[ADDRESS]"
_PLACEHOLDER_PERSON = "[PERSON]"

# DataFog produces numbered placeholders like [PHONE_1], [SSN_2], etc.
# These patterns normalise them to our canonical single-word form.
_DATAFOG_PLACEHOLDER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
	(re.compile(r"\[PHONE_\d+\]"), _PLACEHOLDER_PHONE),
	(re.compile(r"\[SSN_\d+\]"), _PLACEHOLDER_SSN),
	(re.compile(r"\[CREDIT_CARD_\d+\]"), _PLACEHOLDER_CREDIT_CARD),
	(re.compile(r"\[EMAIL_\d+\]"), _PLACEHOLDER_EMAIL),
	# DataFog also emits ZIP, IP_ADDRESS, DOB — map those too
	(re.compile(r"\[ZIP_\d+\]"), "[ZIP]"),
	(re.compile(r"\[IP_ADDRESS_\d+\]"), "[IP_ADDRESS]"),
	(re.compile(r"\[DOB_\d+\]"), "[DOB]"),
]

# ---------------------------------------------------------------------------
# Fallback regex patterns for PII types DataFog is expected to handle
# ---------------------------------------------------------------------------
# These ensure scrubbing works even if DataFog is unavailable or a no-op stub.

# Phone numbers: (555) 123-4567, 555-123-4567, 555.123.4567, +1-555-123-4567
_PHONE_PATTERN = re.compile(
	r"(?:\+\d{1,3}[-.\s]?)?"  # optional international prefix
	r"(?:\(\d{3}\)\s?|\d{3}[-.\s])"  # area code: (555) or 555- or 555.
	r"\d{3}[-.\s]?\d{4}"  # subscriber number
)

# SSN: 123-45-6789
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

# Credit card numbers: 4111-1111-1111-1111, 4111 1111 1111 1111, 4111111111111111
_CREDIT_CARD_PATTERN = re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b")

# Email addresses: user@example.com
_EMAIL_PATTERN = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# ---------------------------------------------------------------------------
# Supplemental regex patterns (what DataFog's regex tier does not cover)
# ---------------------------------------------------------------------------

# US street addresses: require a leading number so "Main Street" alone doesn't match.
_ADDRESS_PATTERN = re.compile(
	r"\b\d+\s+[A-Za-z0-9\s]+"
	r"(?:Street|St|Avenue|Ave|Boulevard|Blvd|Road|Rd|Drive|Dr"
	r"|Lane|Ln|Court|Ct|Way|Place|Pl|Parkway|Pkwy|Highway|Hwy)"
	r"(?:\.|\b)"
	r"(?:[,\s]+[A-Za-z\s]+,\s*[A-Z]{2}\s+\d{5}(?:-\d{4})?)?",
	re.IGNORECASE,
)

# Honorific-anchored person names only.  Detects "Mr. John Smith" but not
# bare "John Smith", trading recall for precision to avoid false positives on
# technology names and sentence-starting capitalised words.
_PERSON_PATTERN = re.compile(
	r"\b(?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?)\s+"
	r"[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*",
)

# ---------------------------------------------------------------------------
# Lazy-initialised DataFog instance (avoids import-time side effects)
# ---------------------------------------------------------------------------

_datafog: DataFog | None = None


def _get_datafog() -> DataFog:
	"""Return the shared DataFog instance, creating it on first call."""
	global _datafog
	if _datafog is None:
		_datafog = DataFog()
	return _datafog


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalise_datafog_placeholders(text: str) -> str:
	"""Replace DataFog's numbered placeholders with our canonical form."""
	for pattern, replacement in _DATAFOG_PLACEHOLDER_PATTERNS:
		text = pattern.sub(replacement, text)
	return text


def _apply_fallback_patterns(text: str) -> str:
	"""Apply regex fallbacks for PII types DataFog is expected to handle.

	These catch phone numbers, SSNs, credit cards, and emails that DataFog
	may have missed (e.g. when running with a stub/no-op backend).
	Order matters: SSN before phone to avoid 3-2-4 patterns being consumed
	by the phone regex; credit cards before phone for the same reason.
	"""
	text = _CREDIT_CARD_PATTERN.sub(_PLACEHOLDER_CREDIT_CARD, text)
	text = _SSN_PATTERN.sub(_PLACEHOLDER_SSN, text)
	text = _PHONE_PATTERN.sub(_PLACEHOLDER_PHONE, text)
	text = _EMAIL_PATTERN.sub(_PLACEHOLDER_EMAIL, text)
	return text


def _apply_supplemental_patterns(text: str) -> str:
	"""Apply address and person-name regex patterns."""
	# Addresses first (longer match, reduces confusion with name patterns)
	text = _ADDRESS_PATTERN.sub(_PLACEHOLDER_ADDRESS, text)
	text = _PERSON_PATTERN.sub(_PLACEHOLDER_PERSON, text)
	return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def scrub_deliverable(text: str) -> str:
	"""Scrub PII from deliverable text before it reaches the user or disk.

	Combines DataFog regex-based detection (phone, SSN, credit card, email,
	IP, DOB, ZIP) with supplemental patterns for physical addresses and
	honorific-prefixed person names.

	Args:
	    text: Raw deliverable text that may contain PII.

	Returns:
	    Text with PII replaced by category-specific placeholders.
	    Empty or whitespace-only input is returned unchanged.

	Notes:
	    Name detection is limited to honorific-prefixed names (Mr./Ms./Dr.
	    etc.).  Bare first+last names are not redacted by this function to
	    avoid false positives on technology terms.  For full NER-based name
	    detection, install datafog[nlp].
	"""
	if not text or not text.strip():
		return text

	# Step 1: DataFog handles phone, SSN, credit card, email, IP, DOB, ZIP
	result = _get_datafog().process(text, anonymize=True, method="redact")
	scrubbed = result.get("anonymized", text)

	# Step 2: Normalise DataFog's numbered placeholders to our canonical form
	scrubbed = _normalise_datafog_placeholders(scrubbed)

	# Step 3: Fallback regex for phone, SSN, credit card, email
	# (catches anything DataFog missed, e.g. when running with a stub backend)
	scrubbed = _apply_fallback_patterns(scrubbed)

	# Step 4: Supplemental patterns for addresses and person names
	scrubbed = _apply_supplemental_patterns(scrubbed)

	return scrubbed
