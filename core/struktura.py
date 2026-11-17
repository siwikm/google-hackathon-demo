"""Contract structure for the document preview: title, parties, § sections, numbered clauses, sub-items.

Every block keeps the number of the paragraph it came from (`p`, 1-based, same as the agent's [Pn]),
so risk anchors from the agent map straight onto the rendered document.
"""

import re
from typing import Any

from .tekst import CELL_SEP

SECTION = re.compile(r"^§\s*(\d+[a-z]?)\.?\s*(.*)$")
NUM_HEADING = re.compile(r"^(\d{1,2})\.\s+(.{2,70})$")
CLAUSE = re.compile(r"^(\d{1,2})[.)]\s+(.*)$")
SUB = re.compile(r"^([a-z])\)\s+(.*)$")
ROLE = re.compile(r"\s*\(([A-ZĄĆĘŁŃÓŚŹŻ][\wąćęłńóśźż ]{2,40})\)\.?\s*$")
META = re.compile(r"^(zawart[aey]|made as of|dated|sporządzon)", re.I)
TITLE = re.compile(r"\b(umowa|agreement|aneks|porozumienie|contract)\b", re.I)
LINE = re.compile(r"^[\s._…\-–|]*$|_{4,}")
CONNECTORS = {"a", "oraz", "and", "pomiędzy:", "pomiędzy", "between:", "between"}


def ladny_tytul(text: str) -> str:
    """'ZAKAZ KONKURENCJI (⚠️ RED RISK)' -> 'Zakaz konkurencji (⚠️ RED RISK)'."""
    head, sep, tail = text.partition(" (")
    if head.isupper():
        head = head[:1] + head[1:].lower()
    return head + (sep + tail if sep else "")


def struktura(akapity: list[str]) -> list[dict[str, Any]]:
    has_paragraph_signs = any(SECTION.match(a) for a in akapity)
    blocks: list[dict[str, Any]] = []
    in_body = False
    has_title = False
    for p, text in enumerate(akapity, start=1):
        block: dict[str, Any] = {"p": p, "tekst": text}
        numbered_heading = NUM_HEADING.match(text)
        if m := SECTION.match(text):
            block |= {"typ": "sekcja", "nr": f"§ {m.group(1)}", "tytul": ladny_tytul(m.group(2))}
            in_body = True
        elif (
            not has_paragraph_signs
            and numbered_heading
            and not text.rstrip().endswith((".", ";", ",", ":"))
            and len(text.split()) <= 8
        ):
            block |= {
                "typ": "sekcja",
                "nr": f"{numbered_heading.group(1)}.",
                "tytul": numbered_heading.group(2),
            }
            in_body = True
        elif CELL_SEP in text:
            block |= {"typ": "wiersz", "komorki": [c.strip() for c in text.split(CELL_SEP)]}
        elif LINE.search(text):
            block |= {"typ": "podpis"}
        elif in_body and (m := CLAUSE.match(text)):
            block |= {"typ": "klauzula", "nr": f"{m.group(1)}.", "tresc": m.group(2)}
        elif m := SUB.match(text):
            block |= {"typ": "pod", "nr": f"{m.group(1)})", "tresc": m.group(2)}
        elif in_body:
            block |= {"typ": "tekst"}
        elif not has_title and (TITLE.search(text) and (text.isupper() or len(text) < 140)):
            block |= {"typ": "tytul"}
            has_title = True
        elif META.match(text):
            block |= {"typ": "meta"}
        elif text.lower() in CONNECTORS:
            block |= {"typ": "lacznik"}
        elif m := ROLE.search(text):
            block |= {"typ": "strona", "rola": m.group(1), "tresc": text[: m.start()].strip()}
        else:
            block |= {"typ": "wstep"}
        blocks.append(block)
    return blocks
