"""Screening names and contract text against the MSWiA sanctions list (osoby + podmioty).

Persons match when surname and first name occur in the same paragraph, in any order and inflected
("Błażej Reiss", "Reissa Błażeja"). Companies match on their exact name token sequence (legal forms
dropped), because generic words like "agency" or "trans" would otherwise match ordinary contract text.
Identifiers (NIP/KRS/PESEL) from the list are matched as well.
"""

import re
from contextlib import closing
from functools import lru_cache
from typing import Any

from . import db
from .tekst import cyfry, tokeny

ID_RE = re.compile(r"\d[\d\- ]{8,}\d")
FOOTNOTE_RE = re.compile(r"^\s*\[\d+\]")  # footnote rows at the bottom of the xlsx sheets


def _stem_match(required: str, words: set[str]) -> bool:
    """Exact token, or a shared stem for longer tokens (Polish inflection: Reiss -> Reissa)."""
    if required in words:
        return True
    if len(required) < 5:
        return False
    stem = required[: max(4, len(required) - 2)]
    return any(w.startswith(stem) for w in words)


def _contains_sequence(seq: list[str], words: list[str]) -> bool:
    n = len(seq)
    return any(words[i : i + n] == seq for i in range(len(words) - n + 1))


def _numery(text: str) -> set[str]:
    """NIP/KRS/REGON/PESEL-like numbers (9-11 digits) with separators removed."""
    return {d for d in (cyfry(m.group()) for m in ID_RE.finditer(text or "")) if 9 <= len(d) <= 11}


@lru_cache(maxsize=1)
def wpisy() -> tuple[dict[str, Any], ...]:
    """Active list entries with the tokens a match requires."""
    db.upewnij_sie()
    with closing(db.polacz(readonly=True)) as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM sankcje WHERE data_wykreslenia IS NULL")]
    out = []
    for r in rows:
        if FOOTNOTE_RE.match(r["nazwa"]):
            continue
        main = re.split(r"[\n(]", r["nazwa"])[0]
        toks = tokeny(main)
        if r["rodzaj"] == "osoba":
            required = [t for t in toks if len(t) >= 2][:2]  # SURNAME First-name; patronymics optional
            if len(required) < 2:
                continue
        else:
            required = toks
            if not required or (len(required) == 1 and len(required[0]) < 5):
                continue  # too ambiguous to screen by name alone
        r["wymagane"] = required
        r["numery"] = _numery(r["dane"] or "")
        out.append(r)
    return tuple(out)


def _pasuje(entry: dict[str, Any], words: list[str]) -> bool:
    if entry["rodzaj"] == "osoba":
        bag = set(words)
        return all(_stem_match(t, bag) for t in entry["wymagane"])
    return _contains_sequence(entry["wymagane"], words)


def _trafienie(entry: dict[str, Any], dopasowanie: str, **extra: Any) -> dict[str, Any]:
    return {
        "nazwa_na_liscie": entry["nazwa"].replace("\n", " "),
        "rodzaj": entry["rodzaj"],
        "dopasowanie": dopasowanie,
        "dane_identyfikacyjne": (entry["dane"] or "").replace("\n", " ")[:200],
        "uzasadnienie": (entry["uzasadnienie"] or "").replace("\n", " ")[:300],
        "data_wpisu": entry["data_wpisu"],
        **extra,
    }


def sprawdz_nazwy(nazwy: list[str]) -> list[dict[str, Any]]:
    hits = []
    for name in nazwy:
        words = tokeny(name)
        numbers = _numery(name)
        for entry in wpisy():
            if _pasuje(entry, words):
                hits.append(_trafienie(entry, "nazwa", zapytanie=name))
            elif entry["numery"] & numbers:
                hits.append(_trafienie(entry, "identyfikator", zapytanie=name))
    return hits


def skanuj_akapity(akapity: list[str]) -> list[dict[str, Any]]:
    """Every list entry whose name or identifier appears in a paragraph of the contract."""
    hits = []
    for nr, text in enumerate(akapity, start=1):
        words = tokeny(text)
        numbers = _numery(text)
        for entry in wpisy():
            if _pasuje(entry, words):
                hits.append(_trafienie(entry, "nazwa", akapit=nr, fragment=text))
            elif entry["numery"] & numbers:
                hits.append(_trafienie(entry, "identyfikator", akapit=nr, fragment=text))
    return hits
