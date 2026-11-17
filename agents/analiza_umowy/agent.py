"""Scenario 1: review one contract.

The LLM reads the contract, extracts parties, payment details and dimensions, and compares clauses with
the group's rules. The VAT register and the sanctions list are checked by tools, and the after-agent
callback treats those checks as authoritative: it adds missed findings, drops contradicted ones,
computes the 0-100 score deterministically and saves the contract to the registry.
"""

import json
import logging
from datetime import date, datetime
from typing import Any, Literal

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools import ToolContext
from pydantic import BaseModel, Field

from core import config, rejestr, sankcje, scoring, vat
from core.db import wiersz_umowy
from core.tekst import akapity_z_wiadomosci, cyfry, tokeny
from core.zasady import (
    ZASADY_PO_ID,
    ZASADY_WYMIAROWE,
    ZIELONY,
    ocen_wymiarowe,
    zasady_dla,
    zasady_umowne,
)

log = logging.getLogger(__name__)


class Strona(BaseModel):
    rola: str = Field(
        description="Zleceniodawca, Zleceniobiorca, Administrator, Podmiot przetwarzający, Podwykonawca"
    )
    nazwa: str
    nip: str | None = Field(default=None, description="NIP z umowy, same cyfry; null jeśli brak")


class KluczowyZapis(BaseModel):
    etykieta: str = Field(
        description="np. Przedmiot, Okres obowiązywania, Wynagrodzenie, Wypowiedzenie, Kary"
    )
    wartosc: str = Field(description="maks. 8 słów, bez pełnego zdania, np. '45 000 PLN netto / mies.'")
    akapit: int = Field(description="numer akapitu [Pn], z którego pochodzi zapis")
    cytat: str = Field(description="dosłowny fragment tego akapitu (bez znacznika [Pn])")


class Platnosc(BaseModel):
    kwota: str | None = None
    termin: str | None = None
    rachunek: str | None = Field(default=None, description="numer rachunku dokładnie jak w umowie")
    akapit: int | None = None
    cytat: str | None = None


class Ryzyko(BaseModel):
    kategoria: str
    poziom: Literal["CZERWONY", "ZOLTY"]
    zasada_id: str = Field(description="id zasady z pobierz_zasady, np. B2B-KARY, ALL-SANKCJE, ALL-VAT")
    opis: str = Field(description="na czym polega odstępstwo i dlaczego to ryzyko (1-2 zdania)")
    akapit: int | None = Field(default=None, description="numer akapitu [Pn] z ryzykownym zapisem")
    cytat: str = Field(
        description="dosłowny, możliwie krótki fragment akapitu (bez [Pn]); pusty gdy zapisu brak"
    )
    rekomendacja: str = Field(description="konkretna propozycja zmiany zapisu")


class Wymiary(BaseModel):
    """Same dimensions as the registry (English values, like the repository JSON)."""

    services_scope: str | None = None
    ip_transfer_moment: str | None = Field(
        default=None, description="np. 'Upon acceptance of monthly report'"
    )
    non_compete_months: int | None = None
    max_penalties_percent: float | None = None
    governing_law: str | None = None
    jurisdiction: str | None = None
    sub_processing_rules: str | None = None
    breach_notification_hours: int | None = None
    audit_rights: str | None = None
    termination_data_policy: str | None = Field(default=None, description="null gdy umowa tego nie reguluje")
    liability_limit_pln: float | None = None
    payment_term_days: int | None = Field(
        default=None, description="termin płatności faktury w dniach; null gdy umowa go nie podaje"
    )
    rate_indexation: str | None = Field(
        default=None,
        description="klauzula waloryzacji stawek, np. 'Annual CPI (GUS) indexation'; null gdy jej brak",
    )
    rate_indexation_mode: Literal["annex", "invoice"] | None = Field(
        default=None,
        description="annex = nowa stawka wymaga aneksu, invoice = wystarczy wyższa faktura, "
        "null gdy umowa tego nie określa",
    )
    ksef_emergency_mode: str | None = Field(
        default=None,
        description="zapisy o fakturach przy niedostępności/awarii KSeF (offline, e-mail z kodem QR), "
        "np. 'Offline: PDF with QR code by e-mail, sent to KSeF later'; null gdy umowa ich nie zawiera",
    )
    sign_date: str | None = Field(default=None, description="YYYY-MM-DD")
    signoff_date: str | None = Field(default=None, description="data akceptacji (sign-off) YYYY-MM-DD")


class Zgodnosc(BaseModel):
    zasada_id: str = Field(description="id spełnionej zasady, np. B2B-KARY")
    akapit: int | None = Field(
        default=None, description="numer akapitu [Pn], w którym widać spełnienie zasady"
    )
    uwaga: str = Field(description="2-5 słów, np. 'limit 10%', 'sąd w Łodzi'")


class AnalizaUmowy(BaseModel):
    typ_umowy: Literal["B2B", "DPA", "NDA", "INNA"]
    tytul: str
    strony: list[Strona] = Field(description="strony umowy ORAZ wszyscy podwykonawcy/dalsze podmioty")
    podsumowanie: str = Field(description="3-4 zdania dla menedżera")
    kluczowe_zapisy: list[KluczowyZapis]
    platnosc: Platnosc | None = None
    ryzyka: list[Ryzyko] = Field(description="tylko odstępstwa ZOLTY/CZERWONY; zgodnych zapisów nie wypisuj")
    zgodnosc: list[Zgodnosc] = Field(
        default_factory=list,
        description="zasady oceniane z zapisów umowy (typu umowy oraz ALL-* poza ALL-SANKCJE i ALL-VAT), "
        "które umowa SPEŁNIA, z akapitem",
    )
    wymiary: Wymiary


# ---------------------------------------------------------------- tools


def pobierz_zasady(typ_umowy: str, tool_context: ToolContext) -> dict:
    """Pobiera zasady (bazę wiedzy) Grupy Pelion dla typu umowy: B2B, DPA (umowa powierzenia),
    NDA (umowa o zachowaniu poufności) albo INNA.

    Wywołaj jako pierwsze, po rozpoznaniu typu umowy.
    """
    zasady = zasady_dla(typ_umowy)
    tool_context.state["typ_umowy"] = typ_umowy.upper()
    return {"zasady": zasady}


def sprawdz_vat(nip: str, rachunki: list[str], tool_context: ToolContext) -> dict:
    """Sprawdza kontrahenta w wykazie podatników VAT Ministerstwa Finansów (biała lista).

    Zwraca status VAT, nazwę z rejestru i dla każdego rachunku z umowy, czy jest w wykazie dla tego NIP.

    Args:
        nip: NIP kontrahenta (nie epruf S.A.), z umowy.
        rachunki: wszystkie numery rachunków bankowych z umowy, dokładnie jak w tekście.
    """
    wynik = vat.sprawdz(nip, rachunki)
    tool_context.state["vat"] = wynik
    return wynik


def sprawdz_sankcje(nazwy: list[str], tool_context: ToolContext) -> dict:
    """Sprawdza osoby i podmioty na liście sankcyjnej MSWiA (osoby i podmioty).

    Sprawdza podane nazwy oraz dodatkowo cały tekst umowy (każdy akapit).

    Args:
        nazwy: nazwy wszystkich stron, podwykonawców, dalszych podmiotów przetwarzających
            i osób fizycznych wymienionych w umowie.
    """
    trafienia = sankcje.sprawdz_nazwy(nazwy) + sankcje.skanuj_akapity(tool_context.state.get("akapity", []))
    unikalne = {h["nazwa_na_liscie"]: h for h in reversed(trafienia)}
    wynik = {
        "sprawdzono_nazw": len(nazwy),
        "trafienia": list(unikalne.values()),
        "wpisow_na_liscie": len(sankcje.wpisy()),
    }
    tool_context.state["sankcje"] = wynik
    return wynik


# ---------------------------------------------------------------- callbacks


def zapamietaj_tekst(callback_context: CallbackContext) -> None:
    """Keep the contract paragraphs in state; tools and the final callback quote from them."""
    content = callback_context.user_content
    text = "\n".join(p.text for p in (content.parts if content else []) if p.text)
    callback_context.state["akapity"] = akapity_z_wiadomosci(text)
    for key in ("vat", "sankcje", "wynik", "analiza"):
        callback_context.state[key] = None


def _akapit_z(akapity: list[str], predicate) -> tuple[int | None, str]:
    for nr, text in enumerate(akapity, start=1):
        if predicate(text):
            return nr, text
    return None, ""


def _ryzyko_sankcyjne(hit: dict[str, Any], akapity: list[str]) -> dict[str, Any]:
    nr, text = hit.get("akapit"), hit.get("fragment")
    if not nr:
        surname = tokeny(hit["nazwa_na_liscie"])[:1]
        nr, text = _akapit_z(akapity, lambda t: bool(surname) and surname[0] in tokeny(t))
    return {
        "kategoria": "Sankcje",
        "poziom": "CZERWONY",
        "zasada_id": "ALL-SANKCJE",
        "opis": f"Podmiot z umowy figuruje na liście sankcyjnej MSWiA jako „{hit['nazwa_na_liscie']}” "
        f"(wpis z {hit.get('data_wpisu') or 'b.d.'}).",
        "akapit": nr,
        "cytat": text or "",
        "rekomendacja": "Wstrzymać podpisanie umowy, usunąć podmiot z listy podwykonawców i zgłosić sprawę do compliance.",
    }


def _ryzyko_vat(wynik: dict[str, Any], rachunek: dict[str, Any] | None, akapity: list[str]) -> dict[str, Any]:
    if rachunek:
        nrb = rachunek.get("nrb") or cyfry(rachunek["rachunek"])
        nr, _ = _akapit_z(akapity, lambda t: nrb in cyfry(t))
        return {
            "kategoria": "Biała lista VAT",
            "poziom": "CZERWONY",
            "zasada_id": "ALL-VAT",
            "opis": f"Rachunek {vat.formatuj_rachunek(nrb)} nie występuje w wykazie VAT dla NIP {wynik['nip']} "
            f"({wynik.get('nazwa') or 'b.d.'}; w wykazie {wynik.get('liczba_rachunkow_w_wykazie', 0)} rachunków).",
            "akapit": nr,
            "cytat": rachunek["rachunek"],
            "rekomendacja": "Płatność tylko na rachunek z białej listy; zażądać potwierdzenia rachunku od kontrahenta.",
        }
    nr, text = _akapit_z(akapity, lambda t: wynik["nip"] in cyfry(t))
    return {
        "kategoria": "Biała lista VAT",
        "poziom": "CZERWONY",
        "zasada_id": "ALL-VAT",
        "opis": f"Kontrahent NIP {wynik['nip']}: status VAT „{wynik.get('status_vat') or 'brak w wykazie'}”.",
        "akapit": nr,
        "cytat": text,
        "rekomendacja": "Nie zawierać umowy do czasu wyjaśnienia statusu VAT kontrahenta.",
    }


def _vat_fallback(analiza: dict[str, Any], akapity: list[str]) -> dict[str, Any] | None:
    """Run the VAT check if the model skipped the tool."""
    nips = [
        cyfry(s.get("nip") or "")
        for s in analiza.get("strony", [])
        if "podwykonawc" not in s.get("rola", "").lower()
    ]
    nips = [n for n in nips if len(n) == 10 and n not in config.NIP_WLASNY]
    if not nips:
        return None
    return vat.sprawdz(nips[0], vat.rachunki_w_tekscie("\n".join(akapity)))


UWAGA_ZGODNOSCI = {"B2B-WALOR": "zapis o waloryzacji", "B2B-KSEF": "tryb awaryjny KSeF"}


def _akapit_wynagrodzenia(analiza: dict[str, Any]) -> int | None:
    zapis = next(
        (
            k
            for k in analiza.get("kluczowe_zapisy") or []
            if "wynagrodz" in str(k.get("etykieta", "")).lower()
        ),
        {},
    )
    return zapis.get("akapit") or (analiza.get("platnosc") or {}).get("akapit")


def _wymus_zasady_wymiarowe(
    analiza: dict[str, Any], ryzyka: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Rate indexation, payment term, KSeF: the level comes from the extracted dimensions, not from the
    model's finding, so thresholds hold and these rules never turn red unless the payment term says so.

    Returns the findings and the model's compliance list with these three rules re-decided.
    """
    llm_risk = {r.get("zasada_id"): r for r in ryzyka if r.get("zasada_id") in ZASADY_WYMIAROWE}
    llm_ok = {z.get("zasada_id"): z for z in analiza.get("zgodnosc") or []}
    ryzyka = [r for r in ryzyka if r.get("zasada_id") not in ZASADY_WYMIAROWE]
    zgodnosc = [z for z in analiza.get("zgodnosc") or [] if z.get("zasada_id") not in ZASADY_WYMIAROWE]
    if analiza.get("typ_umowy") != "B2B":
        return ryzyka, zgodnosc

    wymiary = analiza.get("wymiary") or {}
    platnosc = analiza.get("platnosc") or {}
    akapit_wyn = _akapit_wynagrodzenia(analiza)
    for ocena in ocen_wymiarowe(wymiary):
        zid = ocena["zasada_id"]
        zasada = ZASADY_PO_ID[zid]
        domyslny_akapit = platnosc.get("akapit") if zid == "B2B-TERMIN" else akapit_wyn
        if ocena["poziom"] == ZIELONY:
            ok = llm_ok.get(zid) or {
                "zasada_id": zid,
                "akapit": domyslny_akapit,
                "uwaga": UWAGA_ZGODNOSCI.get(zid, ocena["opis"]),
            }
            if zid == "B2B-WALOR" and not wymiary.get("rate_indexation_mode"):
                # green, but nobody knows yet whether a new rate needs an annex or just a higher invoice
                ok = {**ok, "rekomendacja": zasada["rekomendacja"]}
            zgodnosc.append(ok)
            continue
        llm = llm_risk.get(zid) or {}
        termin_jest = zid == "B2B-TERMIN" and wymiary.get("payment_term_days") is not None
        cytat = llm.get("cytat") or (platnosc.get("cytat") if termin_jest else "") or ""
        risk = {
            "kategoria": zasada["kategoria"],
            "poziom": ocena["poziom"],
            "zasada_id": zid,
            # the payment term's wording carries the day count and the threshold, so it always wins
            "opis": ocena["opis"] if zid == "B2B-TERMIN" else (llm.get("opis") or ocena["opis"]),
            "akapit": llm.get("akapit") or domyslny_akapit,
            "cytat": cytat,
            "rekomendacja": zasada["rekomendacja"],
        }
        if ocena.get("krytycznosc"):
            risk["krytycznosc"] = ocena["krytycznosc"]
        ryzyka.append(risk)
    return ryzyka, zgodnosc


def finalizuj(callback_context: CallbackContext) -> None:
    state = callback_context.state
    analiza = state.get("analiza")
    if isinstance(analiza, str):
        analiza = json.loads(analiza)
    if not analiza:
        return
    akapity: list[str] = state.get("akapity") or []
    ryzyka: list[dict[str, Any]] = list(analiza.get("ryzyka") or [])

    # Sanctions: the list check is authoritative.
    hits = list(((state.get("sankcje") or {}).get("trafienia")) or [])
    if not state.get("sankcje"):
        hits = sankcje.skanuj_akapity(akapity)
    llm_sank = [r for r in ryzyka if r.get("zasada_id") == "ALL-SANKCJE" and r.get("cytat")]
    ryzyka = [r for r in ryzyka if r.get("zasada_id") != "ALL-SANKCJE"]
    for hit in {h["nazwa_na_liscie"]: h for h in hits}.values():
        risk = _ryzyko_sankcyjne(hit, akapity)
        # keep the model's tighter quote (just the name) when it points at the same person/company
        surname = tokeny(hit["nazwa_na_liscie"])[:1]
        same = next((r for r in llm_sank if surname and surname[0] in tokeny(r["cytat"])), None)
        if same:
            risk["cytat"], risk["akapit"] = same["cytat"], same.get("akapit") or risk["akapit"]
        risk["dowod"] = {"zrodlo": "Lista sankcyjna MSWiA (03.11.2026)", **hit}
        ryzyka.append(risk)

    # VAT register: authoritative too.
    wynik_vat = state.get("vat") or _vat_fallback(analiza, akapity)
    ryzyka = [r for r in ryzyka if r.get("zasada_id") != "ALL-VAT"]
    if wynik_vat and not wynik_vat.get("blad"):
        dowod = {"zrodlo": f"Wykaz podatników VAT MF ({wynik_vat.get('zrodlo')})", **wynik_vat}
        if wynik_vat.get("status_vat") != "Czynny":
            ryzyka.append({**_ryzyko_vat(wynik_vat, None, akapity), "dowod": dowod})
        for rachunek in wynik_vat.get("rachunki", []):
            if not rachunek.get("na_liscie"):
                ryzyka.append({**_ryzyko_vat(wynik_vat, rachunek, akapity), "dowod": dowod})

    ryzyka, zgodnosc_llm = _wymus_zasady_wymiarowe(analiza, ryzyka)

    ryzyka.sort(key=lambda r: (r.get("poziom") != "CZERWONY", scoring.krytycznosc(r) != "KRYTYCZNA"))
    for i, r in enumerate(ryzyka, start=1):
        r["id"] = f"R{i}"
    score = scoring.oblicz(ryzyka)

    nazwa_pliku = state.get("nazwa_pliku") or f"analiza_{datetime.now():%Y%m%d_%H%M%S}.txt"
    zapis = None
    if analiza.get("typ_umowy") in ("B2B", "DPA"):
        kontrahent = next(
            (
                s
                for s in analiza.get("strony", [])
                if cyfry(s.get("nip") or "") not in config.NIP_WLASNY
                and "podwykonawc" not in s.get("rola", "").lower()
                and "epruf" not in s.get("nazwa", "").lower()
            ),
            {},
        )
        row = wiersz_umowy(
            {
                **(analiza.get("wymiary") or {}),
                "file_name": nazwa_pliku,
                "contractor": kontrahent.get("nazwa"),
                "nip": cyfry(kontrahent.get("nip") or "") or None,
                "status": "NOWA_ANALIZA",
                "score": score["wartosc"],
                "sign_date": (analiza.get("wymiary") or {}).get("sign_date") or date.today().isoformat(),
                "signoff_date": (analiza.get("wymiary") or {}).get("signoff_date")
                or date.today().isoformat(),
            },
            analiza["typ_umowy"],
            "analiza",
        )
        try:
            rejestr.zapisz(row)
            zapis = {"ok": True, "backend": rejestr.backend(), "file_name": nazwa_pliku}
        except Exception as e:  # registry is a side effect; the analysis result still goes to the UI
            log.exception("Zapis do rejestru nie powiódł się")
            zapis = {"ok": False, "backend": rejestr.backend(), "blad": str(e)[:300]}

    # Rules of this contract type: a rule is compliant unless a finding names it.
    flagged = {r.get("zasada_id") for r in ryzyka}
    typ_rules = zasady_umowne(analiza.get("typ_umowy"))
    zgodnosc = [
        z for z in zgodnosc_llm if z.get("zasada_id") in typ_rules and z.get("zasada_id") not in flagged
    ]

    state["wynik"] = {
        **analiza,
        "ryzyka": ryzyka,
        "zgodnosc": zgodnosc,
        "zasady": {
            "typ": analiza.get("typ_umowy"),
            "liczba": len(typ_rules),
            "zgodne": len([z for z in typ_rules if z not in flagged]),
        },
        "score": score,
        "vat": wynik_vat,
        "sankcje": {"trafienia": hits, "wpisow_na_liscie": len(sankcje.wpisy())},
        "nazwa_pliku": nazwa_pliku,
        "zapis_rejestru": zapis,
    }


root_agent = LlmAgent(
    name="analiza_umowy",
    model=config.MODEL,
    generate_content_config=config.model_config(),
    description="Analiza umowy: podsumowanie, ryzyka względem zasad Grupy Pelion, biała lista VAT, sankcje MSWiA.",
    instruction="""Jesteś radcą prawnym i ekspertem compliance w Grupie Pelion (epruf S.A.).
Użytkownik przesyła treść umowy podzieloną na akapity oznaczone [P1], [P2], ...

Kroki (wykonaj wszystkie):
1. Rozpoznaj typ umowy (B2B = świadczenie usług, DPA = umowa powierzenia przetwarzania danych, NDA = umowa o zachowaniu poufności / confidentiality and nondisclosure agreement, INNA) i wywołaj `pobierz_zasady`.
2. Wywołaj `sprawdz_vat` z NIP-em kontrahenta (nie epruf S.A., NIP 9471958279) i WSZYSTKIMI numerami rachunków bankowych z umowy. W przypadku braku numeru NIP lub braku alternatywnego zagranicznego TAXID, podbij umowę o jeden poziom ryzyka i wskaz to jako obszar do uzupełnienia.
3. Wywołaj `sprawdz_sankcje` z nazwami WSZYSTKICH stron, podwykonawców, dalszych podmiotów przetwarzających i osób fizycznych z umowy.
4. Porównaj zapisy umowy z każdą zasadą. Do `ryzyka` wpisz tylko odstępstwa (ZOLTY albo CZERWONY) z `zasada_id`.
   - Trafienie na liście sankcyjnej => ryzyko ALL-SANKCJE, CZERWONY.
   - Rachunek spoza wykazu VAT albo status VAT inny niż „Czynny” => ryzyko ALL-VAT, CZERWONY.
   - Gdy zasady nie da się ocenić, bo umowa jej nie reguluje, a zasada tego wymaga => CZERWONY z pustym cytatem (poza wyjątkiem niżej).
   - Wyjątek, tylko umowy B2B: brak zapisu o waloryzacji stawek (B2B-WALOR), o terminie płatności (B2B-TERMIN) albo o trybie awaryjnym KSeF (B2B-KSEF) => ZOLTY, nigdy CZERWONY. Termin płatności: do 14 dni zgodny, 15-30 dni ZOLTY, powyżej 30 dni CZERWONY.
   - ALL-KSEF oceniaj tylko w umowach, w których strona wystawia faktury (wynagrodzenie, płatności); w innych pomiń ją całkowicie. Przekazanie wizualizacji z kodem QR e-mailem WYŁĄCZNIE przy niedostępności lub awarii KSeF to tryb awaryjny (B2B-KSEF), a nie „dodatkowy wymóg wysyłki PDF” z progu żółtego ALL-KSEF.
   - ALL-RODO-KLAUZULA dotyczy danych reprezentantów i osób kontaktowych stron; ogólne zdanie o przestrzeganiu przepisów o ochronie danych to nie jest klauzula informacyjna ani odesłanie do polityki prywatności.
5. `cytat` i `kluczowe_zapisy[].cytat` muszą być DOSŁOWNYM fragmentem jednego akapitu (skopiuj znak w znak, bez znacznika [Pn]), a `akapit` to numer tego akapitu.
6. W `zgodnosc` wypisz każdą zasadę typu umowy (B2B-*, DPA-* albo NDA-*) oraz ALL-KSEF, ALL-RODO-KLAUZULA i ALL-KORUPCJA, którą umowa SPEŁNIA: `zasada_id`, numer akapitu i krótką uwagę (np. „limit 10%”).
7. `wymiary` wypełnij po angielsku, w stylu rejestru (np. ip_transfer_moment: "Upon acceptance of monthly report", jurisdiction: "Common Court in Lodz, Poland").
   Dla B2B zawsze ustal: payment_term_days (liczba dni, null gdy brak terminu), rate_indexation (null gdy brak waloryzacji), rate_indexation_mode (annex / invoice / null gdy umowa nie mówi, jak wprowadzić nową stawkę) i ksef_emergency_mode (null gdy umowa nie reguluje faktur przy niedostępności lub awarii KSeF).
8. Pisz po polsku (poza `wymiary`). Zwróć wynik zgodnie ze schematem.""",
    tools=[pobierz_zasady, sprawdz_vat, sprawdz_sankcje],
    output_schema=AnalizaUmowy,
    output_key="analiza",
    before_agent_callback=zapamietaj_tekst,
    after_agent_callback=finalizuj,
)
