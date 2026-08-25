"""Detect personal and secret data on the way into memory.

A memory layer accumulates whatever an agent happened to see: a support
transcript with a card number, a stack trace with a bearer token, a pasted
config with an AWS key. Every one of those then survives indefinitely and gets
re-injected into future sessions. When Mem0 was asked on Hacker News how it
handled this, the answer was "we prompt the model not to store it", and the
follow-up — *"Do you just rely on the LLM to follow instructions perfectly?"* —
went unanswered. This is the non-prompt answer.

**Checksums over regexes wherever one exists.** A bare sixteen-digit regex
matches order numbers, and under a redact policy that silently destroys real
data. Card numbers get Luhn, IBANs get mod-97, and US SSNs get their
structural rules, so those three only fire on strings that could actually be
what they look like. Detectors without a checksum are deliberately narrow.

Nothing here calls a model. Detection runs on every write, and a write path
that depends on an LLM is one that fails when the LLM does.
"""

from __future__ import annotations

import re
from abc import abstractmethod
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

REDACTION = "[redacted:{kind}]"


@dataclass(frozen=True, slots=True)
class PiiMatch:
    kind: str
    start: int
    end: int
    value: str

    @property
    def preview(self) -> str:
        """Enough to recognise the finding without reproducing the secret."""
        if len(self.value) <= 4:
            return "*" * len(self.value)
        return f"{self.value[:2]}…{self.value[-2:]}"


@runtime_checkable
class PiiDetector(Protocol):
    name: str

    @abstractmethod
    def scan(self, text: str, /) -> list[PiiMatch]:
        """Return every match, ordered by position."""
        ...


# --- checksums -------------------------------------------------------------


def luhn_valid(digits: str) -> bool:
    """The check digit every payment card carries.

    Without it, "order 4111111111111111" and "invoice 1234567812345678" are
    indistinguishable, and one of them is not a card.
    """
    if not digits.isdigit() or not 12 <= len(digits) <= 19:
        return False
    total, parity = 0, len(digits) % 2
    for index, char in enumerate(digits):
        value = int(char)
        if index % 2 == parity:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def iban_valid(candidate: str) -> bool:
    """ISO 13616 mod-97: rearrange, letters to numbers, remainder must be 1."""
    compact = candidate.replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", compact):
        return False
    rotated = compact[4:] + compact[:4]
    try:
        numeric = "".join(str(int(c, 36)) for c in rotated)
    except ValueError:
        return False
    return int(numeric) % 97 == 1


def ssn_plausible(candidate: str) -> bool:
    """US SSA structural rules: no 000/666/9xx area, no 00 group, no 0000 serial.

    These exclusions remove most of the false positives a bare \\d{3}-\\d{2}-\\d{4}
    picks up from dates, part numbers and phone fragments.
    """
    digits = candidate.replace("-", "").replace(" ", "")
    if len(digits) != 9 or not digits.isdigit():
        return False
    area, group, serial = digits[:3], digits[3:5], digits[5:]
    if area in {"000", "666"} or area.startswith("9"):
        return False
    return group != "00" and serial != "0000"


# --- patterns --------------------------------------------------------------

_EMAIL = re.compile(r"\b[\w.%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# Anchored on digits at both ends. The obvious `(?:\d[ -]?){12,19}` lets the
# match end on a separator, so redacting it swallows the following space and
# silently glues two words together.
_CARD = re.compile(r"\b\d(?:[ -]?\d){11,18}\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}[ ]?[A-Z0-9]{1,4}\b")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_PHONE = re.compile(r"\+\d{1,3}[ -]?\(?\d{2,4}\)?[ -]?\d{3,4}[ -]?\d{3,4}\b")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

_SECRET_PREFIXES = re.compile(
    r"""\b(
        sk-[A-Za-z0-9_\-]{16,}          # OpenAI
      | sk-ant-[A-Za-z0-9_\-]{16,}      # Anthropic
      | kx_[A-Za-z0-9_\-]{16,}          # Kortex's own keys
      | gh[pousr]_[A-Za-z0-9]{16,}      # GitHub
      | xox[baprs]-[A-Za-z0-9-]{10,}    # Slack
      | AKIA[0-9A-Z]{16}                # AWS access key id
      | AIza[0-9A-Za-z_\-]{35}          # Google
      | glpat-[A-Za-z0-9_\-]{20,}       # GitLab
    )\b""",
    re.VERBOSE,
)

_PRIVATE_V4 = re.compile(r"^(?:10\.|127\.|192\.168\.|169\.254\.|172\.(?:1[6-9]|2\d|3[01])\.)")


class RegexPiiDetector(PiiDetector):
    """The default detector: patterns, plus a checksum wherever one exists."""

    name = "regex"

    def scan(self, text: str, /) -> list[PiiMatch]:
        if not text:
            return []
        matches: list[PiiMatch] = []

        for match in _EMAIL.finditer(text):
            matches.append(PiiMatch("email", match.start(), match.end(), match.group()))

        for match in _SECRET_PREFIXES.finditer(text):
            matches.append(PiiMatch("secret", match.start(), match.end(), match.group()))

        for match in _CARD.finditer(text):
            raw = match.group()
            if luhn_valid(re.sub(r"[ -]", "", raw)):
                matches.append(PiiMatch("card", match.start(), match.end(), raw))

        for match in _IBAN.finditer(text):
            if iban_valid(match.group()):
                matches.append(PiiMatch("iban", match.start(), match.end(), match.group()))

        for match in _SSN.finditer(text):
            if ssn_plausible(match.group()):
                matches.append(PiiMatch("ssn", match.start(), match.end(), match.group()))

        for match in _PHONE.finditer(text):
            matches.append(PiiMatch("phone", match.start(), match.end(), match.group()))

        for match in _IPV4.finditer(text):
            raw = match.group()
            octets = raw.split(".")
            if any(int(o) > 255 for o in octets):
                continue
            # Private and loopback ranges identify no one; flagging them would
            # bury the real findings under every log line an agent ever saw.
            if _PRIVATE_V4.match(raw):
                continue
            matches.append(PiiMatch("ip", match.start(), match.end(), raw))

        return _dedupe_overlaps(matches)


def _dedupe_overlaps(matches: list[PiiMatch]) -> list[PiiMatch]:
    """Keep the longest match per span.

    A card number inside an IBAN, or an email inside a longer token, would
    otherwise be redacted twice and corrupt the surrounding text.
    """
    ordered = sorted(matches, key=lambda m: (m.start, -(m.end - m.start)))
    kept: list[PiiMatch] = []
    for match in ordered:
        if kept and match.start < kept[-1].end:
            continue
        kept.append(match)
    return kept


def redact(text: str, matches: list[PiiMatch]) -> str:
    """Replace each match with a labelled placeholder, right to left.

    Right to left so earlier offsets stay valid as the string shrinks.
    """
    out = text
    for match in sorted(matches, key=lambda m: m.start, reverse=True):
        out = out[: match.start] + REDACTION.format(kind=match.kind) + out[match.end :]
    return out


def summarise(matches: list[PiiMatch]) -> dict[str, int]:
    """Counts by kind — what gets stored on the row.

    Counts, never values: a `pii_flags` column holding the secrets it found
    would be a worse leak than the one it is reporting.
    """
    counts: dict[str, int] = {}
    for match in matches:
        counts[match.kind] = counts.get(match.kind, 0) + 1
    return counts


_singleton: PiiDetector | None = None


def get_pii_detector() -> PiiDetector:
    global _singleton
    if _singleton is None:
        _singleton = RegexPiiDetector()
    return _singleton
