"""Pure, versioned comparison normalization."""

from __future__ import annotations

import re
import unicodedata

_HONORIFICS = {"mr", "mrs", "ms", "miss", "dr"}
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "cfa", "cfp"}
_FIRM_SUFFIXES = {
    "llc",
    "llp",
    "lp",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "ltd",
    "limited",
    "company",
    "co",
    "pllc",
}
_STATES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct",
    "delaware": "de", "district of columbia": "dc", "florida": "fl",
    "georgia": "ga", "hawaii": "hi", "idaho": "id", "illinois": "il",
    "indiana": "in", "iowa": "ia", "kansas": "ks", "kentucky": "ky",
    "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn",
    "mississippi": "ms", "missouri": "mo", "montana": "mt",
    "nebraska": "ne", "nevada": "nv", "new hampshire": "nh",
    "new jersey": "nj", "new mexico": "nm", "new york": "ny",
    "north carolina": "nc", "north dakota": "nd", "ohio": "oh",
    "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa",
    "rhode island": "ri", "south carolina": "sc", "south dakota": "sd",
    "tennessee": "tn", "texas": "tx", "utah": "ut", "vermont": "vt",
    "virginia": "va", "washington": "wa", "west virginia": "wv",
    "wisconsin": "wi", "wyoming": "wy",
}
NICKNAMES = {
    "bob": "robert", "rob": "robert", "bobby": "robert",
    "liz": "elizabeth", "beth": "elizabeth", "bill": "william",
    "will": "william", "kate": "katherine", "kathy": "katherine",
    "jim": "james", "jimmy": "james", "mike": "michael",
}


def _ascii(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().casefold())
    return "".join(
        character for character in text if not unicodedata.combining(character)
    )


def words(value: object) -> list[str]:
    return [
        part
        for part in re.sub(r"[^a-z0-9]+", " ", _ascii(value)).split()
        if part
    ]


def crd(value: object) -> str:
    """Return the opaque CRD identifier with surrounding whitespace removed."""

    return str(value or "").strip()


def email(value: object) -> str:
    normalized = _ascii(value).replace(" ", "")
    return (
        normalized
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized)
        else ""
    )


def person_name(value: object) -> str:
    parts = words(value)
    return " ".join(part for part in parts if part not in _HONORIFICS | _SUFFIXES)


def first_name(value: object, *, aliases: bool = False) -> str:
    normalized = person_name(value).split(" ", 1)[0]
    return NICKNAMES.get(normalized, normalized) if aliases else normalized


def firm(value: object) -> str:
    parts = words(str(value or "").replace("&", " and "))
    normalized = [part for part in parts if part not in _FIRM_SUFFIXES]
    while normalized and normalized[-1] == "and":
        normalized.pop()
    return " ".join(normalized)


def city(value: object) -> str:
    return " ".join(words(value))


def state(value: object) -> str:
    normalized = " ".join(words(value))
    return _STATES.get(normalized, normalized if len(normalized) == 2 else normalized)


def zip_code(value: object) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[:5] if len(digits) >= 5 else digits
