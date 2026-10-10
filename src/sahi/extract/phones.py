from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

import phonenumbers


class PhoneClass(StrEnum):
    TOLL_FREE = "TOLL_FREE"
    UAN = "UAN"
    MOBILE = "MOBILE"
    LANDLINE = "LANDLINE"
    SHORT_CODE = "SHORT_CODE"
    FOREIGN = "FOREIGN"


@dataclass(frozen=True, slots=True)
class PhoneMatch:
    canonical: str
    raw: str
    kind: PhoneClass
    display: str
    search_variants: tuple[str, ...]


CALLING_CUES = (
    "call",
    "dial",
    "helpline",
    "toll free",
    "कॉल",
    "डायल",
    "हेल्पलाइन",
)
PRICE_RE = re.compile(r"(?:₹|\brs\.?|\binr)\s*$", re.IGNORECASE)
LONG_CANDIDATE_RE = re.compile(r"(?<![\w])(?:\+\s*)?\d(?:[\d\s().-]{7,}\d)(?![\w])")
SHORT_RE = re.compile(r"(?<!\w)\d{3,6}(?!\w)")


def ascii_digits(text: str) -> str:
    result = []
    for character in text:
        try:
            result.append(str(unicodedata.decimal(character)))
        except (TypeError, ValueError):
            result.append(character)
    return "".join(result)


def _quoted_unique(*values: str) -> tuple[str, ...]:
    variants: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = re.sub(r"\s+", " ", value.strip())
        if not cleaned or cleaned in seen:
            continue
        variants.append(f'"{cleaned}"')
        seen.add(cleaned)
    return tuple(variants)


def _variants(raw: str, digits: str, kind: PhoneClass, canonical: str) -> tuple[str, ...]:
    if kind == PhoneClass.TOLL_FREE and len(digits) in {10, 11}:
        tail = digits[4:]
        grouped = f"1800 {tail[:3]} {tail[3:]}"
        dashed = f"1800-{tail[:3]}-{tail[3:]}"
        return _quoted_unique(digits, grouped, dashed, raw)
    if kind == PhoneClass.UAN:
        tail = digits[4:]
        return _quoted_unique(
            digits,
            f"1860 {tail[:3]} {tail[3:]}",
            f"1860-{tail[:3]}-{tail[3:]}",
            raw,
        )
    if kind in {PhoneClass.MOBILE, PhoneClass.LANDLINE, PhoneClass.FOREIGN}:
        try:
            parsed = phonenumbers.parse(canonical, None)
            e164 = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
            national = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)
            international = phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
            )
        except phonenumbers.NumberParseException:
            e164 = canonical
            national = digits
            international = canonical
        national_digits = re.sub(r"\D", "", national)
        return _quoted_unique(
            e164,
            e164.lstrip("+"),
            national_digits,
            national,
            international,
            raw,
        )
    return _quoted_unique(digits)


def _build(raw: str, digits: str, kind: PhoneClass, canonical: str) -> PhoneMatch:
    display = canonical
    if kind in {PhoneClass.MOBILE, PhoneClass.LANDLINE, PhoneClass.FOREIGN}:
        try:
            parsed = phonenumbers.parse(canonical, None)
            display = phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
            )
        except phonenumbers.NumberParseException:
            pass
    return PhoneMatch(
        canonical,
        raw.strip(),
        kind,
        display,
        _variants(raw, digits, kind, canonical),
    )


def display_phone(value: str) -> str:
    """Return a human-readable international rendering without changing identity."""

    match = normalise_phone(value)
    return match.display if match else value


def normalise_phone(value: str) -> PhoneMatch | None:
    text = ascii_digits(value).strip()
    explicit_plus = text.startswith("+")
    digits = re.sub(r"\D", "", text)
    if not digits:
        return None
    if digits.startswith("1800") and len(digits) in {10, 11}:
        return _build(value, digits, PhoneClass.TOLL_FREE, digits)
    if digits.startswith("1860") and len(digits) == 11:
        return _build(value, digits, PhoneClass.UAN, digits)
    if explicit_plus and not digits.startswith("91"):
        try:
            parsed = phonenumbers.parse("+" + digits, None)
            if phonenumbers.is_possible_number(parsed):
                canonical = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
                return _build(value, digits, PhoneClass.FOREIGN, canonical)
        except phonenumbers.NumberParseException:
            return None
        return None
    local = digits
    had_trunk_prefix = len(local) == 11 and local.startswith("0")
    if len(local) == 12 and local.startswith("91"):
        local = local[2:]
    elif len(local) == 11 and local.startswith("0"):
        local = local[1:]
    if len(local) != 10:
        return None
    parsed_type = None
    if had_trunk_prefix:
        try:
            parsed_type = phonenumbers.number_type(phonenumbers.parse("+91" + local, None))
        except phonenumbers.NumberParseException:
            parsed_type = None
    if local[0] in "6789" and (
        not had_trunk_prefix
        or parsed_type
        in {phonenumbers.PhoneNumberType.MOBILE, phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE}
    ):
        return _build(value, local, PhoneClass.MOBILE, "+91" + local)
    if explicit_plus or digits.startswith("0"):
        return _build(value, local, PhoneClass.LANDLINE, "+91" + local)
    return None


def _price_before(text: str, start: int) -> bool:
    return bool(PRICE_RE.search(text[max(0, start - 8) : start]))


def _id_context(text: str, start: int) -> bool:
    prefix = text[max(0, start - 12) : start].lower()
    return bool(re.search(r"(?:order\s*(?:id)?|pnr|ticket)\s*$", prefix))


def find_phones(text: str) -> list[PhoneMatch]:
    """Extract phone-like values from prose, preserving first-seen order."""

    normalized = ascii_digits(text)
    found: list[PhoneMatch] = []
    seen: set[str] = set()
    occupied: list[tuple[int, int]] = []

    def add_candidate(raw: str, start: int, end: int) -> None:
        if (start and normalized[start - 1].isalnum()) or (
            end < len(normalized) and normalized[end].isalnum()
        ):
            return
        if _price_before(normalized, start) or _id_context(normalized, start):
            return
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 6 or (
            len(digits) == 12 and not digits.startswith("91") and not raw.strip().startswith("+")
        ):
            return
        match = normalise_phone(raw)
        if match and match.canonical not in seen:
            found.append(match)
            seen.add(match.canonical)
            occupied.append((start, end))

    for candidate in phonenumbers.PhoneNumberMatcher(normalized, "IN"):
        add_candidate(candidate.raw_string, candidate.start, candidate.end)
    for candidate in LONG_CANDIDATE_RE.finditer(normalized):
        add_candidate(candidate.group(0), candidate.start(), candidate.end())
    for candidate in SHORT_RE.finditer(normalized):
        if any(start <= candidate.start() < end for start, end in occupied):
            continue
        sentence_start = max(
            normalized.rfind(mark, 0, candidate.start()) for mark in (".", "!", "?", "\n")
        )
        endings = [
            position
            for mark in (".", "!", "?", "\n")
            if (position := normalized.find(mark, candidate.end())) >= 0
        ]
        sentence_end = min(endings) if endings else len(normalized)
        sentence = normalized[sentence_start + 1 : sentence_end].casefold()
        digits = candidate.group(0)
        if not any(cue in sentence for cue in CALLING_CUES):
            continue
        prefix = normalized[max(0, candidate.start() - 12) : candidate.start()].casefold()
        year_context = len(digits) == 4 and bool(re.search(r"(?:year|founded|since)\s*$", prefix))
        if year_context or _price_before(normalized, candidate.start()):
            continue
        if digits not in seen:
            found.append(_build(candidate.group(0), digits, PhoneClass.SHORT_CODE, digits))
            seen.add(digits)
    return found
