"""Pure, versioned comparison normalization."""

from __future__ import annotations

import re
import unicodedata

_HONORIFICS = {"mr", "mrs", "ms", "miss", "dr"}
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "cfa", "cfp"}
_FIRM_SUFFIXES = {"llc", "inc", "incorporated", "corp", "corporation", "ltd", "company", "co"}
_STREET = {"street": "st", "avenue": "ave", "road": "rd", "boulevard": "blvd", "drive": "dr", "lane": "ln", "suite": "ste", "north": "n", "south": "s", "east": "e", "west": "w"}
_STATES = {
    "massachusetts": "ma", "new york": "ny", "california": "ca", "texas": "tx",
    "florida": "fl", "illinois": "il", "colorado": "co", "washington": "wa",
    "pennsylvania": "pa", "new jersey": "nj", "virginia": "va", "ohio": "oh",
    "georgia": "ga", "north carolina": "nc", "michigan": "mi", "arizona": "az",
}
NICKNAMES = {
    "bob": "robert", "rob": "robert", "bobby": "robert", "liz": "elizabeth",
    "beth": "elizabeth", "bill": "william", "will": "william", "kate": "katherine",
    "kathy": "katherine", "jim": "james", "jimmy": "james", "mike": "michael",
}


def _ascii(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().casefold())
    return "".join(character for character in text if not unicodedata.combining(character))


def words(value: object) -> list[str]:
    return [part for part in re.sub(r"[^a-z0-9]+", " ", _ascii(value)).split() if part]


def crd(value: object) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return text if re.fullmatch(r"\d+", text) else ""


def email(value: object) -> str:
    normalized = _ascii(value).replace(" ", "")
    return normalized if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized) else ""


def person_name(value: object) -> str:
    parts = words(value)
    return " ".join(part for part in parts if part not in _HONORIFICS | _SUFFIXES)


def first_name(value: object, *, aliases: bool = False) -> str:
    normalized = person_name(value).split(" ", 1)[0]
    return NICKNAMES.get(normalized, normalized) if aliases else normalized


def firm(value: object) -> str:
    parts = ["and" if part == "&" else part for part in words(str(value or "").replace("&", " and "))]
    return " ".join(part for part in parts if part not in _FIRM_SUFFIXES)


def street(value: object) -> str:
    return " ".join(_STREET.get(part, part) for part in words(value))


def city(value: object) -> str:
    return " ".join(words(value))


def state(value: object) -> str:
    normalized = " ".join(words(value))
    return _STATES.get(normalized, normalized[:2] if len(normalized) == 2 else normalized)


def zip_code(value: object) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[:5] if len(digits) >= 5 else digits
