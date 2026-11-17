"""Text helpers: name normalisation for sanctions matching, paragraph extraction from TXT/DOCX."""

import io
import re
import unicodedata
import zipfile
from xml.etree import ElementTree

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
# Legal-form words and fillers dropped before comparing company names.
STOP_TOKENS = {
    "sp",
    "z",
    "o",
    "oo",
    "s",
    "a",
    "sa",
    "ska",
    "spolka",
    "k",
    "j",
    "c",
    "sc",
    "ltd",
    "llc",
    "inc",
    "gmbh",
    "oddzial",
    "w",
    "polsce",
    "obecnie",
    "inaczej",
    "pao",
    "ooo",
    "ao",
    "zao",
    "jsc",
    "plc",
    "corp",
}
AKAPIT_RE = re.compile(r"^\[P(\d+)\]\s?(.*)$")


def bez_diakrytykow(text: str) -> str:
    text = text.replace("ł", "l").replace("Ł", "L")
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def tokeny(text: str) -> list[str]:
    """Lowercase ASCII word tokens without legal-form noise."""
    words = re.findall(r"[a-z0-9]+", bez_diakrytykow(text).lower())
    return [w for w in words if w not in STOP_TOKENS]


def cyfry(text: str) -> str:
    return re.sub(r"\D", "", text)


CELL_SEP = " | "
LOWER_START = re.compile(r"^[a-ząćęłńóśźż]")
SUB_ITEM = re.compile(r"^[a-z]\)")
CONNECTORS = {"a", "i", "oraz", "and", "pomiędzy", "pomiędzy:", "between", "between:"}


def _p_text(p: ElementTree.Element) -> str:
    return "".join(t.text or "" for t in p.iter(f"{WORD_NS}t"))


def _docx_akapity(data: bytes) -> list[str]:
    """Body paragraphs in document order; each table row becomes one paragraph with cells joined by ' | '."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    body = root.find(f"{WORD_NS}body")
    out: list[str] = []
    for child in body if body is not None else []:
        if child.tag == f"{WORD_NS}p":
            out.append(_p_text(child))
        elif child.tag == f"{WORD_NS}tbl":
            for tr in child.iter(f"{WORD_NS}tr"):
                cells = [
                    " ".join(t for t in (_p_text(p).strip() for p in tc.iter(f"{WORD_NS}p")) if t)
                    for tc in tr.findall(f"{WORD_NS}tc")
                ]
                cells = [c for c in cells if c]
                if cells:
                    out.append(CELL_SEP.join(cells))
        elif child.tag == f"{WORD_NS}sdt":  # content controls wrap ordinary paragraphs
            out.extend(_p_text(p) for p in child.iter(f"{WORD_NS}p"))
    return out


def _sklej(lines: list[str]) -> list[str]:
    """Normalise whitespace and glue hard-wrapped lines (a line starting lowercase continues the previous one)."""
    out: list[str] = []
    for raw in lines:
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        if (
            out
            and LOWER_START.match(line)
            and not SUB_ITEM.match(line)
            and line.lower() not in CONNECTORS
            and out[-1].lower() not in CONNECTORS
            and CELL_SEP not in out[-1]
            and not re.search(r"[.:;!?…)]$", out[-1])
        ):
            out[-1] = f"{out[-1]} {line}"
        else:
            out.append(line)
    return out


def akapity_z_bajtow(nazwa: str, data: bytes) -> list[str]:
    """Non-empty paragraphs of a TXT/MD or DOCX file."""
    name = nazwa.lower()
    if name.endswith(".docx"):
        return _sklej(_docx_akapity(data))
    if name.endswith((".txt", ".md")):
        return _sklej(data.decode("utf-8", errors="replace").splitlines())
    raise ValueError("Obsługiwane pliki: TXT, MD, DOCX.")


def tekst_dla_agenta(akapity: list[str]) -> str:
    """Numbered paragraphs, the format the agent quotes from: '[P1] ...'."""
    return "\n".join(f"[P{i}] {p}" for i, p in enumerate(akapity, start=1))


def akapity_z_wiadomosci(text: str) -> list[str]:
    """Inverse of tekst_dla_agenta; falls back to plain lines when the text has no [Pn] markers."""
    numbered = [AKAPIT_RE.match(line.strip()) for line in text.splitlines()]
    if any(numbered):
        return [m.group(2) for m in numbered if m]
    return [line.strip() for line in text.splitlines() if line.strip()]
