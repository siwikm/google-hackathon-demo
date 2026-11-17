"""Deterministic risk score 0-100 from the list of findings, so the number does not drift between runs."""

from typing import Any

from .zasady import ZASADY_PO_ID

WAGI = {
    ("KRYTYCZNA", "CZERWONY"): 60,
    ("WYSOKA", "CZERWONY"): 35,
    ("WYSOKA", "ZOLTY"): 15,
    ("SREDNIA", "CZERWONY"): 25,
    ("SREDNIA", "ZOLTY"): 10,
    ("NISKA", "CZERWONY"): 15,
    ("NISKA", "ZOLTY"): 5,
}
WYNIK_SANKCJI = 100  # a sanctions hit sets the score outright, whatever else the contract says


def punkty(zasada: dict[str, Any], poziom: str) -> int:
    """Points one finding of this rule adds to the score at this level (rules overview in the UI)."""
    if zasada["id"] == "ALL-SANKCJE" and poziom == "CZERWONY":
        return WYNIK_SANKCJI
    return WAGI.get((zasada["krytycznosc"], poziom), 0)


def krytycznosc(r: dict[str, Any]) -> str:
    """The finding's own criticality (e.g. a payment term of 60+ days) or its rule's."""
    zasada = ZASADY_PO_ID.get(r.get("zasada_id") or "")
    return r.get("krytycznosc") or (zasada["krytycznosc"] if zasada else "SREDNIA")


def oblicz(ryzyka: list[dict[str, Any]]) -> dict[str, Any]:
    skladniki = []
    for r in ryzyka:
        punkty = WAGI.get((krytycznosc(r), r.get("poziom")), 0)
        if punkty:
            skladniki.append({"ryzyko": r.get("id"), "zasada_id": r.get("zasada_id"), "punkty": punkty})
    if any(r.get("zasada_id") == "ALL-SANKCJE" and r.get("poziom") == "CZERWONY" for r in ryzyka):
        wartosc, powod = WYNIK_SANKCJI, "Trafienie na liście sankcyjnej MSWiA: współpraca niedopuszczalna."
    else:
        wartosc = min(100, sum(s["punkty"] for s in skladniki))
        powod = "Suma wag odstępstw (czerwone i żółte × krytyczność zasady), maksymalnie 100."
    poziom = (
        "KRYTYCZNE"
        if wartosc >= 70
        else "WYSOKIE"
        if wartosc >= 40
        else "UMIARKOWANE"
        if wartosc >= 15
        else "NISKIE"
    )
    return {"wartosc": wartosc, "poziom": poziom, "powod": powod, "skladniki": skladniki}
