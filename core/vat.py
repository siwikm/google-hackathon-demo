"""Client for the Ministry of Finance VAT taxpayer register ("biała lista").

Responses are cached in SQLite per (NIP, date). A saved response in wiedza/vat_cache/<nip>.json is the
offline fallback, so the demo survives API limits or a dead conference Wi-Fi.
"""

import json
import re
from contextlib import closing
from datetime import date, datetime
from typing import Any

import httpx

from . import config, db
from .tekst import cyfry

API = "https://wykazpodatnikowvat.mf.gov.pl/api/search/nip/{nip}"
NRB_RE = re.compile(r"(?:PL\s?)?\d{2}(?:[ \-]?\d{4}){6}")


def normalizuj_rachunek(rachunek: str) -> str:
    return cyfry(rachunek)[-26:]


def formatuj_rachunek(nrb: str) -> str:
    return f"{nrb[:2]} {' '.join(nrb[i : i + 4] for i in range(2, 26, 4))}" if len(nrb) == 26 else nrb


def rachunki_w_tekscie(text: str) -> list[str]:
    return [m.group() for m in NRB_RE.finditer(text)]


def _pobierz(nip: str, dzien: str) -> tuple[dict[str, Any], str]:
    db.upewnij_sie()
    with closing(db.polacz()) as conn:
        row = conn.execute("SELECT odpowiedz FROM vat_cache WHERE nip=? AND data=?", (nip, dzien)).fetchone()
        if row:
            return json.loads(row["odpowiedz"]), "cache"
        try:
            resp = httpx.get(
                API.format(nip=nip),
                params={"date": dzien},
                headers={"Accept": "application/json"},
                timeout=10,
            )
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError):
            fallback = config.VAT_CACHE_DIR / f"{nip}.json"
            if fallback.exists():
                return json.loads(fallback.read_text(encoding="utf-8")), "plik offline"
            raise
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO vat_cache VALUES (?, ?, ?, ?)",
                (nip, dzien, json.dumps(payload, ensure_ascii=False), datetime.now().isoformat()),
            )
        return payload, "API MF"


def sprawdz(nip: str, rachunki: list[str], dzien: str | None = None) -> dict[str, Any]:
    nip = cyfry(nip)
    dzien = dzien or date.today().isoformat()
    if len(nip) != 10:
        return {"nip": nip, "blad": "NIP musi mieć 10 cyfr"}
    try:
        payload, zrodlo = _pobierz(nip, dzien)
    except httpx.HTTPError as e:
        return {"nip": nip, "blad": f"Wykaz VAT niedostępny: {e}"}
    subject = (payload.get("result") or {}).get("subject")
    if not subject:
        return {
            "nip": nip,
            "znaleziony": False,
            "zrodlo": zrodlo,
            "rachunki": [{"rachunek": r, "na_liscie": False} for r in rachunki],
        }
    on_list = set(subject.get("accountNumbers") or [])
    return {
        "nip": nip,
        "znaleziony": True,
        "nazwa": subject.get("name"),
        "status_vat": subject.get("statusVat"),
        "adres": subject.get("residenceAddress") or subject.get("workingAddress"),
        "liczba_rachunkow_w_wykazie": len(on_list),
        "rachunki": [
            {"rachunek": r, "nrb": normalizuj_rachunek(r), "na_liscie": normalizuj_rachunek(r) in on_list}
            for r in rachunki
        ],
        "data_sprawdzenia": dzien,
        "id_zapytania": (payload.get("result") or {}).get("requestId"),
        "zrodlo": zrodlo,
    }
