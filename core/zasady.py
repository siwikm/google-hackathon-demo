"""Group contract rules (knowledge base) and their deterministic evaluation against registry rows.

Thresholds come from the green/yellow/red sample contracts in wiedza/ and the approved registry entries.
"""

import re
from typing import Any

ZIELONY, ZOLTY, CZERWONY = "ZIELONY", "ZOLTY", "CZERWONY"

ZASADY: list[dict[str, str]] = [
    {
        "id": "B2B-IP",
        "typ": "B2B",
        "kategoria": "Prawa autorskie",
        "krytycznosc": "WYSOKA",
        "wymaganie": "Przeniesienie autorskich praw majątkowych na Zleceniodawcę",
        "zielony": "z chwilą podpisania protokołu odbioru, na wszystkich polach eksploatacji",
        "zolty": "warunkowo, dopiero po zapłacie wynagrodzenia",
        "czerwony": "brak przeniesienia, tylko licencja",
    },
    {
        "id": "B2B-ZAKAZ",
        "typ": "B2B",
        "kategoria": "Zakaz konkurencji",
        "krytycznosc": "SREDNIA",
        "wymaganie": "Zakaz konkurencji w trakcie umowy i po jej rozwiązaniu",
        "zielony": "co najmniej 12 miesięcy po rozwiązaniu",
        "zolty": "od 1 do 11 miesięcy",
        "czerwony": "brak zakazu konkurencji",
    },
    {
        "id": "B2B-KARY",
        "typ": "B2B",
        "kategoria": "Kary umowne",
        "krytycznosc": "WYSOKA",
        "wymaganie": "Kary umowne z górnym limitem",
        "zielony": "łączny limit kar do 10% wynagrodzenia netto",
        "zolty": "limit powyżej 10% do 20%",
        "czerwony": "limit powyżej 20%, brak limitu albo wyłączenie kar umownych",
    },
    {
        "id": "B2B-SAD",
        "typ": "B2B",
        "kategoria": "Prawo i sąd",
        "krytycznosc": "NISKA",
        "wymaganie": "Prawo polskie, sąd właściwy dla siedziby Zleceniodawcy",
        "zielony": "prawo polskie, sąd w Łodzi",
        "zolty": "-",
        "czerwony": "sąd właściwy dla kontrahenta lub obce prawo",
    },
    {
        "id": "B2B-WALOR",
        "typ": "B2B",
        "kategoria": "Waloryzacja stawek",
        "krytycznosc": "NISKA",
        "wymaganie": "Zapis o waloryzacji stawek wynagrodzenia (wskaźnik, termin, tryb: aneks albo wyższa faktura)",
        "zielony": "umowa zawiera zapis o waloryzacji stawek",
        "zolty": "brak zapisu o waloryzacji stawek",
        "czerwony": "-",
        "rekomendacja": "Skontaktować się z kontrahentem i ustalić, czy zmiana stawki ma wymagać aneksu, "
        "czy wystarczy wyższa faktura; ustalony tryb dopisać do umowy.",
    },
    {
        "id": "B2B-TERMIN",
        "typ": "B2B",
        "kategoria": "Termin płatności",
        "krytycznosc": "SREDNIA",
        "wymaganie": "Termin płatności faktury Zleceniobiorcy",
        "zielony": "do 14 dni",
        "zolty": "od 15 do 30 dni albo brak terminu w umowie (ustawowo 30 dni)",
        "czerwony": "powyżej 30 dni; od 60 dni ryzyko krytyczne",
        "rekomendacja": "Uzgodnić z kontrahentem termin płatności do 14 dni od doręczenia faktury.",
    },
    {
        "id": "B2B-KSEF",
        "typ": "B2B",
        "kategoria": "KSeF – tryb awaryjny",
        "krytycznosc": "NISKA",
        "wymaganie": "Fakturowanie w KSeF z procedurą na tryby offline i awarię KSeF",
        "zielony": "umowa wskazuje kanał przekazania faktury poza KSeF (np. e-mail z kodem QR), "
        "obowiązek dosłania jej do KSeF i moment, od którego biegnie termin płatności",
        "zolty": "brak zapisu o KSeF albo o trybie offline/awarii KSeF",
        "czerwony": "-",
        "rekomendacja": "Uzgodnić z kontrahentem, jak przekaże fakturę przy niedostępności lub awarii KSeF "
        "(np. e-mail z kodem QR) i od kiedy biegnie wtedy termin płatności; ustalenia dopisać do umowy.",
    },
    {
        "id": "B2B-ODBIOR",
        "typ": "B2B",
        "kategoria": "Procedura odbioru prac",
        "krytycznosc": "SREDNIA",
        "wymaganie": "Czas na weryfikację i zgłoszenie uwag do wykonanych usług/etapu prac",
        "zielony": "od 5 do 14 dni roboczych na zgłoszenie uwag od momentu dostarczenia",
        "zolty": "poniżej 5 dni roboczych lub automatyczny odbiór przy braku sprzeciwu",
        "czerwony": "brak procedury odbioru, brak możliwości zgłoszenia poprawek",
    },
    {
        "id": "DPA-PODPOW",
        "typ": "DPA",
        "kategoria": "Dalsze powierzenie",
        "krytycznosc": "WYSOKA",
        "wymaganie": "Dalsze powierzenie danych tylko za zgodą Administratora",
        "zielony": "uprzednia, szczegółowa pisemna zgoda",
        "zolty": "zgoda ogólna z uprzedzeniem min. 7 dni",
        "czerwony": "pełna swoboda bez zgody i bez informowania",
    },
    {
        "id": "DPA-NARUSZ",
        "typ": "DPA",
        "kategoria": "Zgłaszanie naruszeń",
        "krytycznosc": "WYSOKA",
        "wymaganie": "Termin zgłoszenia naruszenia ochrony danych Administratorowi",
        "zielony": "do 24 godzin",
        "zolty": "od 24 do 72 godzin",
        "czerwony": "powyżej 72 godzin",
    },
    {
        "id": "DPA-AUDYT",
        "typ": "DPA",
        "kategoria": "Prawo audytu",
        "krytycznosc": "SREDNIA",
        "wymaganie": "Prawo Administratora do audytów i inspekcji",
        "zielony": "audyty bez istotnych ograniczeń",
        "zolty": "audyt ograniczony (np. raz w roku, tylko audytor zewnętrzny)",
        "czerwony": "brak prawa do audytu",
    },
    {
        "id": "DPA-USUN",
        "typ": "DPA",
        "kategoria": "Usunięcie danych",
        "krytycznosc": "WYSOKA",
        "wymaganie": "Usunięcie lub zwrot danych po zakończeniu umowy (termination_data_policy)",
        "zielony": "usunięcie/zwrot do 30 dni",
        "zolty": "usunięcie/zwrot w terminie dłuższym niż 30 dni",
        "czerwony": "brak zapisu albo brak obowiązku usunięcia danych",
    },
    {
        "id": "DPA-ODPOW",
        "typ": "DPA",
        "kategoria": "Limit odpowiedzialności",
        "krytycznosc": "SREDNIA",
        "wymaganie": "Limit odpowiedzialności Podmiotu przetwarzającego",
        "zielony": "co najmniej 100 000 PLN",
        "zolty": "od 50 000 do 100 000 PLN",
        "czerwony": "poniżej 50 000 PLN",
    },
    {
        "id": "NDA-OKRES",
        "typ": "NDA",
        "kategoria": "Okres ochrony poufności",
        "krytycznosc": "WYSOKA",
        "wymaganie": "Czas trwania zobowiązania do zachowania poufności po zakończeniu rozmów",
        "zielony": "co najmniej 5 lat od wygaśnięcia/rozwiązania rozmów lub bezterminowo",
        "zolty": "od 2 do 4 lat od wygaśnięcia rozmów lub określony od momentu ujawnienia informacji",
        "czerwony": "poniżej 2 lat lub całkowity brak określenia okresu ochrony",
    },
    {
        "id": "NDA-CEL",
        "typ": "NDA",
        "kategoria": "Precyzyjny cel udostępnienia",
        "krytycznosc": "SREDNIA",
        "wymaganie": "Jasno zdefiniowany cel biznesowy przekazania informacji poufnych (Purpose)",
        "zielony": "cel precyzyjnie określony i ograniczony do konkretnej współpracy/projektu",
        "zolty": "cel określony ogólnie (np. ogólne rozmowy handlowe)",
        "czerwony": "brak zdefiniowanego celu lub cel sformułowany skrajnie szeroko (ryzyko wycieku know-how)",
    },
    {
        "id": "ALL-KSEF",
        "typ": "ALL",
        "kategoria": "Zgodność z KSeF",
        "krytycznosc": "WYSOKA",
        "wymaganie": "Klauzula określająca sposób i format wystawiania oraz dostarczania faktur ustrukturyzowanych",
        "zielony": "pełna zgoda na wystawianie faktur ustrukturyzowanych za pośrednictwem KSeF zgodnie z przepisami",
        "zolty": "faktury przesyłane w KSeF, ale z dodatkowym wymogiem wysyłki wizualizacji PDF e-mailem",
        "czerwony": "całkowite wyłączenie KSeF lub brak zapisu o fakturowaniu elektronicznym",
    },
    {
        "id": "ALL-RODO-KLAUZULA",
        "typ": "ALL",
        "kategoria": "Obowiązek informacyjny RODO",
        "krytycznosc": "WYSOKA",
        "wymaganie": "Obecność klauzuli informacyjnej dotyczącej przetwarzania danych kontaktowych reprezentantów stron",
        "zielony": "pełna klauzula informacyjna dla reprezentantów i osób kontaktowych wpisana do umowy lub jako załącznik",
        "zolty": "odesłanie do polityki prywatności na stronie www kontrahenta",
        "czerwony": "całkowity brak klauzuli informacyjnej RODO i brak odesłania do polityki",
    },
    {
        "id": "ALL-KORUPCJA",
        "typ": "ALL",
        "kategoria": "Klauzula antykorupcyjna (ESG)",
        "krytycznosc": "SREDNIA",
        "wymaganie": "Zobowiązanie stron do przestrzegania standardów antykorupcyjnych i etycznych Grupy Kapitałowej",
        "zielony": "pełna klauzula antykorupcyjna wraz z prawem do natychmiastowego rozwiązania umowy w przypadku naruszenia",
        "zolty": "ogólne oświadczenie o przestrzeganiu przepisów prawa bez konkretnych sankcji kontraktowych",
        "czerwony": "brak jakichkolwiek zapisów antykorupcyjnych lub etycznych",
    },
    {
        "id": "ALL-SANKCJE",
        "typ": "ALL",
        "kategoria": "Sankcje",
        "krytycznosc": "KRYTYCZNA",
        "wymaganie": "Żadna strona ani podwykonawca nie może figurować na liście sankcyjnej MSWiA",
        "zielony": "brak trafień",
        "zolty": "-",
        "czerwony": "trafienie na liście sankcyjnej",
    },
    {
        "id": "ALL-VAT",
        "typ": "ALL",
        "kategoria": "Biała lista VAT",
        "krytycznosc": "KRYTYCZNA",
        "wymaganie": "Kontrahent jest czynnym podatnikiem VAT, a rachunek do płatności jest w wykazie MF dla jego NIP",
        "zielony": "status Czynny, rachunek w wykazie",
        "zolty": "-",
        "czerwony": "rachunek spoza wykazu lub status inny niż Czynny",
    },
]
ZASADY_PO_ID = {z["id"]: z for z in ZASADY}


TYPY_UMOW = ("B2B", "DPA", "NDA")
# ALL-* rules checked by tools (VAT register, sanctions list), not read from the contract's clauses.
SPRAWDZANE_NARZEDZIAMI = ("ALL-SANKCJE", "ALL-VAT")
# ALL-* rules that make no sense for a contract type: a DPA or an NDA carries no invoices.
NIE_DOTYCZY = {"ALL-KSEF": ("DPA", "NDA")}


def zasady_dla(typ: str | None) -> list[dict[str, str]]:
    typ = (typ or "").upper()
    if typ not in TYPY_UMOW:
        return list(ZASADY)
    return [z for z in ZASADY if z["typ"] in ("ALL", typ) and typ not in NIE_DOTYCZY.get(z["id"], ())]


def metoda_oceny(zasada_id: str) -> str:
    """How the analysis decides a rule: an external register (rejestr), a threshold in code (prog),
    or Gemini reading the clause (llm)."""
    if zasada_id in SPRAWDZANE_NARZEDZIAMI:
        return "rejestr"
    if zasada_id in ZASADY_WYMIAROWE:
        return "prog"
    return "llm"


def zasady_umowne(typ: str | None) -> list[str]:
    """Ids of the rules judged from the contract's own clauses (the compliance count), for a known type."""
    if (typ or "").upper() not in TYPY_UMOW:
        return []
    return [z["id"] for z in zasady_dla(typ) if z["id"] not in SPRAWDZANE_NARZEDZIAMI]


# Free-text dimension values in the registry: "No deletion", "none", "brak"... mean the clause is missing.
NEGACJE = re.compile(
    r"\b(no deletion|not allowed|no audit|none|brak|nie dotyczy|retain|full freedom|without consent)\b", re.I
)


def usuwanie_danych(policy: Any) -> bool:
    """False when termination_data_policy is missing or says the data is not deleted/returned."""
    text = str(policy or "").strip()
    return bool(text) and not NEGACJE.search(text)


def _dni(text: str) -> int | None:
    m = re.search(r"(\d+)\s*(day|dni)", text, re.I)
    return int(m.group(1)) if m else None


def _ocena(zasada_id: str, poziom: str, opis: str, krytycznosc: str | None = None) -> dict[str, str]:
    out = {
        "zasada_id": zasada_id,
        "poziom": poziom,
        "opis": opis,
        "kategoria": ZASADY_PO_ID[zasada_id]["kategoria"],
    }
    if krytycznosc:  # finding-level override of the rule's criticality (payment term of 60+ days)
        out["krytycznosc"] = krytycznosc
    return out


# Rules judged from dimensions that only the analysis extracts; the repository JSON has no such data.
ZASADY_WYMIAROWE = ("B2B-WALOR", "B2B-TERMIN", "B2B-KSEF")
# Stored in the registry when the analysed contract has no such clause, so NULL keeps meaning "not known".
BRAK_ZAPISU = "None"


def _jest_zapis(value: Any) -> bool:
    text = str(value or "").strip()
    return bool(text) and text.lower() != BRAK_ZAPISU.lower()


def ocen_wymiarowe(row: dict[str, Any]) -> list[dict[str, str]]:
    """Rate indexation, payment term and KSeF emergency mode. None/'None' means the contract has no such clause."""
    out: list[dict[str, str]] = []
    walor = str(row.get("rate_indexation") or "").strip()
    if _jest_zapis(walor):
        out.append(_ocena("B2B-WALOR", ZIELONY, walor))
    else:
        out.append(_ocena("B2B-WALOR", ZOLTY, "Brak zapisu o waloryzacji stawek"))

    days = row.get("payment_term_days")
    if days is None:
        out.append(_ocena("B2B-TERMIN", ZOLTY, "Brak terminu płatności w umowie (ustawowo 30 dni)"))
    elif days <= 14:
        out.append(_ocena("B2B-TERMIN", ZIELONY, f"{days} dni"))
    elif days <= 30:
        out.append(_ocena("B2B-TERMIN", ZOLTY, f"Termin płatności {days} dni (powyżej 14)"))
    elif days < 60:
        out.append(_ocena("B2B-TERMIN", CZERWONY, f"Termin płatności {days} dni (powyżej 30)"))
    else:
        out.append(
            _ocena("B2B-TERMIN", CZERWONY, f"Termin płatności {days} dni (od 60 dni: krytyczne)", "KRYTYCZNA")
        )

    ksef = str(row.get("ksef_emergency_mode") or "").strip()
    if _jest_zapis(ksef):
        out.append(_ocena("B2B-KSEF", ZIELONY, ksef))
    else:
        out.append(_ocena("B2B-KSEF", ZOLTY, "Brak zapisu o trybie offline/awarii KSeF"))
    return out


def ocen_umowe(row: dict[str, Any]) -> list[dict[str, str]]:
    """Every rule outcome (green ones included) for one registry row."""
    typ = (row.get("typ") or "").upper()
    out: list[dict[str, str]] = []
    if typ == "B2B":
        ip = str(row.get("ip_transfer_moment") or "")
        service_only = "service only" in ip.lower()
        if service_only or re.search(r"acceptance|protok", ip, re.I):
            out.append(_ocena("B2B-IP", ZIELONY, ip or "brak danych"))
        elif re.search(r"payment|zapłat", ip, re.I):
            out.append(_ocena("B2B-IP", ZOLTY, f"Przeniesienie IP warunkowe: {ip}"))
        else:
            out.append(_ocena("B2B-IP", CZERWONY, f"Brak przeniesienia IP: {ip or 'brak zapisu'}"))

        months = row.get("non_compete_months")
        if months is None:
            out.append(_ocena("B2B-ZAKAZ", CZERWONY, "Brak zapisu o zakazie konkurencji"))
        elif months >= 12 or (months == 0 and service_only):
            out.append(
                _ocena("B2B-ZAKAZ", ZIELONY, f"{months} mies." + (" (usługa bez IP)" if service_only else ""))
            )
        elif months > 0:
            out.append(_ocena("B2B-ZAKAZ", ZOLTY, f"Zakaz konkurencji tylko {months} mies."))
        else:
            out.append(_ocena("B2B-ZAKAZ", CZERWONY, "Brak zakazu konkurencji"))

        pct = row.get("max_penalties_percent")
        if pct is None or pct <= 0:
            out.append(_ocena("B2B-KARY", CZERWONY, "Brak limitu kar lub kary wyłączone"))
        elif pct <= 10:
            out.append(_ocena("B2B-KARY", ZIELONY, f"Limit kar {pct}%"))
        elif pct <= 20:
            out.append(_ocena("B2B-KARY", ZOLTY, f"Limit kar {pct}% (powyżej 10%)"))
        else:
            out.append(_ocena("B2B-KARY", CZERWONY, f"Limit kar {pct}% (powyżej 20%)"))

        sad = f"{row.get('governing_law') or ''} {row.get('jurisdiction') or ''}"
        if re.search(r"lodz|łódź|łodz", sad, re.I) and re.search(r"polish|polsk", sad, re.I):
            out.append(_ocena("B2B-SAD", ZIELONY, sad.strip()))
        else:
            out.append(_ocena("B2B-SAD", CZERWONY, f"Sąd/prawo: {sad.strip() or 'brak zapisu'}"))

        # Repository rows and contracts analysed before these rules have NULL here: no data, no verdict.
        if row.get("zrodlo") == "analiza" and row.get("rate_indexation") is not None:
            out.extend(ocen_wymiarowe(row))

    if typ == "DPA":
        sub = str(row.get("sub_processing_rules") or "")
        if re.search(r"full freedom|without consent|swobod", sub, re.I) or not sub:
            out.append(
                _ocena("DPA-PODPOW", CZERWONY, f"Dalsze powierzenie bez kontroli: {sub or 'brak zapisu'}")
            )
        elif re.search(r"general|ogóln", sub, re.I):
            out.append(_ocena("DPA-PODPOW", ZOLTY, f"Zgoda ogólna: {sub}"))
        else:
            out.append(_ocena("DPA-PODPOW", ZIELONY, sub))

        hours = row.get("breach_notification_hours")
        if hours is None or hours > 72:
            out.append(
                _ocena(
                    "DPA-NARUSZ",
                    CZERWONY,
                    f"Zgłoszenie naruszenia: {hours if hours is not None else 'brak'} h",
                )
            )
        elif hours > 24:
            out.append(_ocena("DPA-NARUSZ", ZOLTY, f"Zgłoszenie naruszenia: {hours} h"))
        else:
            out.append(_ocena("DPA-NARUSZ", ZIELONY, f"{hours} h"))

        audit = str(row.get("audit_rights") or "")
        if not audit or re.search(r"not allowed|no audit|brak|nie zezwala", audit, re.I):
            out.append(_ocena("DPA-AUDYT", CZERWONY, f"Brak prawa audytu: {audit or 'brak zapisu'}"))
        elif re.search(r"only|annual|once a year|quarterly|remote|raz w roku|wyłącznie", audit, re.I):
            out.append(_ocena("DPA-AUDYT", ZOLTY, f"Audyt ograniczony: {audit}"))
        else:
            out.append(_ocena("DPA-AUDYT", ZIELONY, audit))

        policy = str(row.get("termination_data_policy") or "")
        if not usuwanie_danych(policy):
            out.append(
                _ocena("DPA-USUN", CZERWONY, f"Brak obowiązku usunięcia danych: {policy or 'brak zapisu'}")
            )
        elif (dni := _dni(policy)) is not None and dni > 30:
            out.append(_ocena("DPA-USUN", ZOLTY, f"Usunięcie danych dopiero po {dni} dniach"))
        else:
            out.append(_ocena("DPA-USUN", ZIELONY, policy))

        limit = row.get("liability_limit_pln")
        if limit is None or limit < 50_000:
            out.append(
                _ocena(
                    "DPA-ODPOW",
                    CZERWONY,
                    "Limit odpowiedzialności "
                    + (f"{limit:,.0f} PLN".replace(",", " ") if limit is not None else "brak"),
                )
            )
        elif limit < 100_000:
            out.append(
                _ocena("DPA-ODPOW", ZOLTY, f"Limit odpowiedzialności {limit:,.0f} PLN".replace(",", " "))
            )
        else:
            out.append(_ocena("DPA-ODPOW", ZIELONY, f"{limit:,.0f} PLN".replace(",", " ")))

    if typ == "NDA":
        years = row.get("protection_period_years")
        if years is None or years < 2:
            out.append(_ocena("NDA-OKRES", CZERWONY, f"Okres ochrony poufności: {years if years is not None else 'brak'} lat"))
        elif years < 5:
            out.append(_ocena("NDA-OKRES", ZOLTY, f"Okres ochrony poufności tylko {years} lata"))
        else:
            out.append(_ocena("NDA-OKRES", ZIELONY, f"{years} lat"))

        cel = str(row.get("purpose") or "")
        if not cel:
            out.append(_ocena("NDA-CEL", CZERWONY, "Brak zdefiniowanego celu udostępnienia informacji"))
        elif re.search(r"general|evaluation|ogóln", cel, re.I):
            out.append(_ocena("NDA-CEL", ZOLTY, f"Cel określony ogólnie: {cel}"))
        else:
            out.append(_ocena("NDA-CEL", ZIELONY, cel))
    return out


def odstepstwa(row: dict[str, Any]) -> list[dict[str, str]]:
    """Only the yellow and red rule outcomes."""
    return [o for o in ocen_umowe(row) if o["poziom"] != ZIELONY]
