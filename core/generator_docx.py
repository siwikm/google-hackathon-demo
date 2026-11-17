"""Generate visually diverse .docx contracts for all 40 registry entries.

Each contract is assigned one of 5 distinct visual & structural templates so the documents do not look
cookie-cutter either in Word/Pages/Google Docs or in the web preview.

    uv run python -m core.generator_docx
"""

import hashlib
import io
import zipfile
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from . import config, db

DOCX_DIR = config.WIEDZA / "umowy_docx"

# 5 distinct visual themes for WordprocessingML + web preview
THEMES: list[dict[str, str]] = [
    {
        "id": "kancelaryjny",
        "nazwa": "Klasyczny kancelaryjny",
        "font": "Georgia",
        "accent": "1E293B",
        "bg": "F8FAFC",
        "border": "double",
    },
    {
        "id": "korporacyjny",
        "nazwa": "Korporacyjny z metryczką",
        "font": "Calibri",
        "accent": "1B365D",
        "bg": "EFF6FF",
        "border": "single",
    },
    {
        "id": "tech",
        "nazwa": "Minimalistyczny IT / Agile",
        "font": "Arial",
        "accent": "0F5132",
        "bg": "ECFDF5",
        "border": "thick",
    },
    {
        "id": "ramkowy",
        "nazwa": "Formalny z preambułą",
        "font": "Garamond",
        "accent": "6B1D2F",
        "bg": "FDF2F8",
        "border": "single",
    },
    {
        "id": "enterprise",
        "nazwa": "Enterprise – Karta Umowy",
        "font": "Verdana",
        "accent": "2B547E",
        "bg": "F0F4F8",
        "border": "single",
    },
]


def motyw_dla(nazwa_pliku: str) -> dict[str, str]:
    stem = Path(nazwa_pliku).stem.lower()
    h = int(hashlib.md5(stem.encode("utf-8")).hexdigest()[:8], 16)
    return THEMES[h % len(THEMES)]


def nazwa_docx(file_name: str) -> str:
    return f"{Path(file_name).stem}.docx"


def sciezka_docx(file_name: str) -> Path:
    return DOCX_DIR / nazwa_docx(file_name)


def _sekcja(styl_id: str, nr: int, tytul: str) -> str:
    if styl_id == "tech":
        return f"{nr}. {tytul}"
    return f"§ {nr} {tytul}"


def _akapity_b2b(r: dict[str, Any], styl_id: str) -> list[str]:
    firma = r.get("contractor") or "Kontrahent B2B"
    nip = r.get("nip") or "brak w rejestrze"
    data = r.get("sign_date") or "2026-01-01"
    czas = r.get("duration") or "Czas nieokreślony"
    zakres = r.get("services_scope") or "Usługi doradcze i programistyczne IT"
    ip = r.get("ip_transfer_moment") or "Upon acceptance of monthly report"
    zakaz = r.get("non_compete_months")
    kary = r.get("max_penalties_percent")
    prawo = r.get("governing_law") or "Polish law"
    sad = r.get("jurisdiction") or "Common Court in Lodz, Poland"
    termin = r.get("payment_term_days")
    walor = r.get("rate_indexation")
    ksef = r.get("ksef_emergency_mode")

    out: list[str] = [
        f"UMOWA O ŚWIADCZENIE USŁUG B2B — {firma.upper()}",
        f"Zawarta w dniu {data} w Łodzi (czas obowiązywania: {czas}) pomiędzy:",
    ]
    if styl_id in ("korporacyjny", "enterprise"):
        out.extend(
            [
                "Strona | Dane rejestrowe | Rola w umowie",
                "epruf S.A. | ul. Zbąszyńska 3, 91-342 Łódź, NIP: 9471958279 | Zleceniodawca",
                f"{firma} | NIP: {nip} | Zleceniobiorca",
            ]
        )
    else:
        out.extend(
            [
                "epruf S.A. z siedzibą w Łodzi, ul. Zbąszyńska 3, NIP 9471958279, reprezentowaną przez Zarząd (Zleceniodawca)",
                "oraz",
                f"{firma}, NIP {nip} (Zleceniobiorca)",
            ]
        )
    if styl_id == "ramkowy":
        out.append(
            "Preambuła: Strony zawierają niniejszą umowę współpracy B2B w celu zapewnienia profesjonalnego wsparcia technologicznego dla systemów transakcyjnych Grupy Pelion."
        )

    # § 1
    out.append(_sekcja(styl_id, 1, "PRZEDMIOT WSPÓŁPRACY I CZAS TRWANIA"))
    out.append(
        f"1. Zleceniobiorca zobowiązuje się do profesjonalnego świadczenia usług w zakresie: {zakres}."
    )
    out.append(f"2. Umowa zostaje zawarta na okres: {czas}, z datą wejścia w życie od dnia {data}.")

    # § 2
    out.append(_sekcja(styl_id, 2, "PRAWA WŁASNOŚCI INTELEKTUALNEJ (IP)"))
    if "no ip" in ip.lower() or "service only" in ip.lower():
        out.append(
            f"1. Usługi mają charakter wyłącznie doradczo-utrzymaniowy ({ip}) i nie obejmują tworzenia odrębnych utworów w rozumieniu prawa autorskiego."
        )
    elif "payment" in ip.lower():
        out.append(
            f"1. Zleceniobiorca przenosi na Zleceniodawcę autorskie prawa majątkowe do wytworzonych rezultatów na wszystkich polach eksploatacji dopiero z chwilą zapłaty faktury ({ip})."
        )
    else:
        out.append(
            f"1. W ramach wynagrodzenia Zleceniobiorca przenosi na Zleceniodawcę autorskie prawa majątkowe na wszystkich polach eksploatacji z chwilą podpisania protokołu odbioru ({ip})."
        )

    # § 3
    out.append(_sekcja(styl_id, 3, "ZAKAZ KONKURENCJI"))
    if not zakaz or int(zakaz) <= 0:
        out.append(
            "1. Strony nie ustanawiają odrębnego zakazu konkurencji po rozwiązaniu niniejszej umowy (0 miesięcy)."
        )
    else:
        out.append(
            f"1. Zleceniobiorca zobowiązuje się do powstrzymania się od działalności konkurencyjnej wobec Zleceniodawcy w trakcie trwania umowy oraz przez okres {int(zakaz)} miesięcy po jej rozwiązaniu."
        )

    # § 4
    out.append(_sekcja(styl_id, 4, "ODPOWIEDZIALNOŚĆ I KARY UMOWNE"))
    if kary is None or float(kary) <= 0:
        out.append("1. Odpowiedzialność odszkodowawcza Stron opiera się na zasadach ogólnych Kodeksu cywilnego.")
    else:
        out.append(
            f"1. W razie naruszenia zobowiązań umownych Zleceniodawca może naliczyć kary umowne, przy czym łączny limit kar umownych nie przekroczy {float(kary):g}% wynagrodzenia netto."
        )

    # § 5
    out.append(_sekcja(styl_id, 5, "WYNAGRODZENIE, WALORYZACJA I FAKTUROWANIE KSEF"))
    if termin:
        out.append(
            f"1. Wynagrodzenie płatne jest w terminie {int(termin)} dni od daty doręczenia prawidłowo wystawionej faktury VAT."
        )
    else:
        out.append("1. Wynagrodzenie płatne jest na podstawie faktury VAT wystawionej po zakończeniu miesiąca.")
    if walor and str(walor).lower() != "none":
        out.append(
            f"2. Stawka wynagrodzenia podlega waloryzacji na zasadach: {walor}. Wprowadzenie zwaloryzowanej stawki wymaga pisemnego aneksu."
        )
    else:
        out.append("2. Stawka wynagrodzenia jest stała i umowa nie przewiduje automatycznej klauzuli waloryzacyjnej.")
    if ksef and str(ksef).lower() != "none":
        out.append(
            f"3. Faktury ustrukturyzowane wystawiane są w KSeF. Tryb awaryjny i offline: {ksef}."
        )
    else:
        out.append("3. Faktury doręczane są drogą elektroniczną zgodnie z obowiązującymi przepisami podatkowymi.")

    if styl_id == "enterprise":
        out.extend(
            [
                "Parametr finansowo-prawny | Wartość uzgodniona w umowie",
                f"Termin płatności faktury | {f'{int(termin)} dni' if termin else 'ustawowy'}",
                f"Limit kar umownych | {f'{float(kary):g}%' if kary else 'brak'}",
                f"Okres zakazu konkurencji | {f'{int(zakaz)} mies.' if zakaz else '0 mies.'}",
            ]
        )

    # § 6
    out.append(_sekcja(styl_id, 6, "PROCEDURA ODBIORU USŁUG"))
    out.append(
        "1. Zleceniobiorca przedstawia miesięczne zestawienie wykonanych prac, a Zleceniodawca w terminie 7 dni roboczych dokonuje odbioru lub zgłasza zastrzeżenia."
    )

    # § 7
    out.append(_sekcja(styl_id, 7, "PRAWO WŁAŚCIWE, RODO I KLAUZULA ANTYKORUPCYJNA"))
    out.append(f"1. Prawem właściwym dla umowy jest: {prawo}. Sądem właściwym do rozstrzygania sporów jest: {sad}.")
    out.append(
        "2. Strony realizują obowiązek informacyjny RODO wobec swoich reprezentantów i osób kontaktowych zgodnie z załącznikiem do umowy."
    )
    out.append(
        "3. Zleceniobiorca zobowiązuje się do przestrzegania standardów antykorupcyjnych Grupy Pelion pod rygorem natychmiastowego rozwiązania umowy."
    )
    out.append("____________________ | ____________________")
    return out


def _akapity_dpa(r: dict[str, Any], styl_id: str) -> list[str]:
    firma = r.get("contractor") or "Podmiot Przetwarzający"
    nip = r.get("nip") or "brak w rejestrze"
    data = r.get("sign_date") or "2026-01-01"
    czas = r.get("duration") or "Czas trwania umowy głównej"
    podpow = r.get("sub_processing_rules") or "Prior written consent required"
    godz = r.get("breach_notification_hours") or 24
    audyt = r.get("audit_rights") or "Allowed annually"
    usun = r.get("termination_data_policy") or "Deletion within 30 days"
    limit = r.get("liability_limit_pln") or 100000

    out: list[str] = [
        f"UMOWA POWIERZENIA PRZETWARZANIA DANYCH OSOBOWYCH (DPA) — {firma.upper()}",
        f"Zawarta w dniu {data} w Łodzi (okres obowiązywania: {czas}) pomiędzy:",
    ]
    if styl_id in ("korporacyjny", "enterprise"):
        out.extend(
            [
                "Strona umowy DPA | Identyfikator NIP | Status RODO",
                "epruf S.A. z siedzibą w Łodzi | NIP: 9471958279 | Administrator Danych",
                f"{firma} | NIP: {nip} | Podmiot Przetwarzający",
            ]
        )
    else:
        out.extend(
            [
                "epruf S.A. z siedzibą w Łodzi, ul. Zbąszyńska 3, NIP 9471958279 (Administrator)",
                "a",
                f"{firma}, NIP {nip} (Podmiot przetwarzający)",
            ]
        )

    out.append(_sekcja(styl_id, 1, "PRZEDMIOT I CZAS POWIERZENIA DANYCH"))
    out.append(
        f"1. Administrator powierza Podmiotowi przetwarzającemu dane osobowe w trybie art. 28 RODO na okres: {czas}."
    )

    out.append(_sekcja(styl_id, 2, "DALSZE POWIERZENIE DANYCH (SUB-PROCESSING)"))
    out.append(
        f"1. Zasady korzystania z dalszych podmiotów przetwarzających (podwykonawców): {podpow}."
    )

    out.append(_sekcja(styl_id, 3, "ZGŁASZANIE NARUSZEŃ OCHRONY DANYCH"))
    out.append(
        f"1. Po stwierdzeniu naruszenia ochrony danych osobowych Podmiot przetwarzający zgłasza je Administratorowi nie później niż w terminie {int(godz)} godzin od wykrycia."
    )

    out.append(_sekcja(styl_id, 4, "PRAWO DO AUDYTU I KONTROLI"))
    out.append(
        f"1. Uprawnienia kontrolne i audytowe Administratora wobec Podmiotu przetwarzającego są realizowane na następujących warunkach: {audyt}."
    )

    out.append(_sekcja(styl_id, 5, "USUNIĘCIE LUB ZWROT DANYCH PO ZAKOŃCZENIU UMOWY"))
    out.append(
        f"1. Zasady postępowania z danymi osobowymi po rozwiązaniu lub wygaśnięciu umowy (termination_data_policy): {usun}."
    )

    out.append(_sekcja(styl_id, 6, "LIMIT ODPOWIEDZIALNOŚCI I POSTANOWIENIA KOŃCOWE"))
    out.append(
        f"1. Łączna odpowiedzialność finansowa Podmiotu przetwarzającego z tytułu niniejszej umowy jest ograniczona do kwoty {float(limit):,.0f} PLN.".replace(
            ",", " "
        )
    )
    out.append(
        "2. Strony przekazują swoim reprezentantom klauzule informacyjne RODO oraz zobowiązują się do przestrzegania zasad etycznych i antykorupcyjnych Grupy Pelion."
    )
    out.append("____________________ | ____________________")
    return out


def _akapity_nda(r: dict[str, Any], styl_id: str) -> list[str]:
    firma = r.get("contractor") or "Partner Biznesowy"
    nip = r.get("nip") or "brak w rejestrze"
    data = r.get("sign_date") or "2026-01-01"
    czas = r.get("duration") or "Czas nieokreślony"
    cel = r.get("purpose") or "Business cooperation evaluation"
    lata = r.get("protection_period_years") or 5
    odbiorcy = r.get("permitted_recipients") or "Employees only"
    kara = r.get("contractual_penalty_pln") or 50000
    prawo = r.get("governing_law") or "Polish law"
    sad = r.get("jurisdiction") or "Common Court in Lodz, Poland"

    out: list[str] = [
        f"UMOWA O ZACHOWANIU POUFNOŚCI (NDA) — {firma.upper()}",
        f"Sporządzona w dniu {data} w Łodzi (obowiązywanie: {czas}) pomiędzy:",
    ]
    if styl_id in ("korporacyjny", "enterprise"):
        out.extend(
            [
                "Strona umowy NDA | NIP | Rola",
                "epruf S.A. z siedzibą w Łodzi | 9471958279 | Strona Ujawniająca",
                f"{firma} | {nip} | Strona Otrzymująca",
            ]
        )
    else:
        out.extend(
            [
                "epruf S.A. z siedzibą w Łodzi, ul. Zbąszyńska 3, NIP 9471958279 (Zleceniodawca)",
                "a",
                f"{firma}, NIP {nip} (Zleceniobiorca)",
            ]
        )

    out.append(_sekcja(styl_id, 1, "CEL UDOSTĘPNIENIA INFORMACJI POUFNYCH"))
    out.append(
        f"1. Strony udostępniają sobie informacje poufne w celu: {cel}."
    )

    out.append(_sekcja(styl_id, 2, "UPRAWNIENI ODBIORCY I ZASADY OCHRONY"))
    out.append(
        f"1. Dostęp do informacji poufnych mogą uzyskać wyłącznie następujące kategorie osób: {odbiorcy}."
    )

    out.append(_sekcja(styl_id, 3, "OKRES OCHRONY POUFNOŚCI"))
    out.append(
        f"1. Zobowiązanie do zachowania poufności obowiązuje przez cały czas trwania umowy ({czas}) oraz przez okres {int(lata)} lat po jej wygaśnięciu lub zakończeniu rozmów."
    )

    out.append(_sekcja(styl_id, 4, "KARY UMOWNE I PRAWO WŁAŚCIWE"))
    out.append(
        f"1. Za każde naruszenie obowiązku poufności Strona naruszająca zapłaci karę umowną w wysokości {float(kara):,.0f} PLN.".replace(
            ",", " "
        )
    )
    out.append(f"2. Umowa podlega prawu: {prawo}, a spory rozstrzyga: {sad}.")
    out.append(
        "3. Strony realizują obowiązek informacyjny RODO wobec osób kontaktowych oraz stosują zasady antykorupcyjne Grupy Pelion."
    )
    out.append("____________________ | ____________________")
    return out


def akapity_dla_wiersza(row: dict[str, Any]) -> list[str]:
    """Return paragraphs for a contract row (uses existing file in wiedza/ if present, otherwise builds from row)."""
    fn = row.get("file_name") or ""
    for candidate in (config.DEMO_DIR / fn, config.WIEDZA / fn):
        if candidate.exists() and candidate.suffix.lower() in (".txt", ".docx"):
            from .tekst import akapity_z_bajtow

            return akapity_z_bajtow(candidate.name, candidate.read_bytes())

    styl_id = motyw_dla(fn)["id"]
    typ = (row.get("typ") or "B2B").upper()
    if typ == "DPA":
        return _akapity_dpa(row, styl_id)
    if typ == "NDA":
        return _akapity_nda(row, styl_id)
    return _akapity_b2b(row, styl_id)


def _xml_paragraph(text: str, theme: dict[str, str], idx: int) -> str:
    font = theme["font"]
    accent = theme["accent"]
    bg = theme["bg"]
    styl_id = theme["id"]

    # Table row (`a | b | c`) -> rendered as a Word table by the caller
    is_title = idx == 0
    is_meta = idx == 1
    is_section = text.startswith("§") or (
        styl_id == "tech" and len(text) > 3 and text[0].isdigit() and text[1:3] == ". " and text.isupper()
    )

    if is_title:
        jc = "center" if styl_id in ("kancelaryjny", "ramkowy") else "left"
        bdr = f'<w:pBdr><w:bottom w:val="{theme["border"]}" w:sz="12" w:space="6" w:color="{accent}"/></w:pBdr>'
        shd = f'<w:shd w:val="clear" w:color="auto" w:fill="{bg}"/>' if styl_id in ("korporacyjny", "enterprise") else ""
        return (
            f"<w:p><w:pPr><w:jc w:val=\"{jc}\"/><w:spacing w:before=\"120\" w:after=\"200\"/>{bdr}{shd}</w:pPr>"
            f"<w:r><w:rPr><w:rFonts w:ascii=\"{font}\" w:hAnsi=\"{font}\"/><w:b/>"
            f"<w:color w:val=\"{accent}\"/><w:sz w:val=\"28\"/></w:rPr>"
            f"<w:t>{escape(text)}</w:t></w:r></w:p>"
        )

    if is_meta:
        return (
            f"<w:p><w:pPr><w:spacing w:before=\"60\" w:after=\"160\"/></w:pPr>"
            f"<w:r><w:rPr><w:rFonts w:ascii=\"{font}\" w:hAnsi=\"{font}\"/><w:i/>"
            f"<w:color w:val=\"475569\"/><w:sz w:val=\"20\"/></w:rPr>"
            f"<w:t>{escape(text)}</w:t></w:r></w:p>"
        )

    if is_section:
        shd = f'<w:shd w:val="clear" w:color="auto" w:fill="{bg}"/>' if styl_id in ("ramkowy", "enterprise") else ""
        left_bdr = (
            f'<w:pBdr><w:left w:val="single" w:sz="18" w:space="8" w:color="{accent}"/></w:pBdr>'
            if styl_id in ("korporacyjny", "tech")
            else ""
        )
        jc = "center" if styl_id == "kancelaryjny" else "left"
        return (
            f"<w:p><w:pPr><w:jc w:val=\"{jc}\"/><w:spacing w:before=\"240\" w:after=\"100\"/>{left_bdr}{shd}</w:pPr>"
            f"<w:r><w:rPr><w:rFonts w:ascii=\"{font}\" w:hAnsi=\"{font}\"/><w:b/>"
            f"<w:color w:val=\"{accent}\"/><w:sz w:val=\"23\"/></w:rPr>"
            f"<w:t>{escape(text)}</w:t></w:r></w:p>"
        )

    indent = '<w:ind w:firstLine="420"/>' if styl_id == "kancelaryjny" else ""
    return (
        f"<w:p><w:pPr><w:jc w:val=\"both\"/><w:spacing w:before=\"60\" w:after=\"100\" w:line=\"276\" w:lineRule=\"auto\"/>{indent}</w:pPr>"
        f"<w:r><w:rPr><w:rFonts w:ascii=\"{font}\" w:hAnsi=\"{font}\"/><w:sz w:val=\"21\"/></w:rPr>"
        f"<w:t>{escape(text)}</w:t></w:r></w:p>"
    )


def _xml_table(rows: list[list[str]], theme: dict[str, str]) -> str:
    font = theme["font"]
    accent = theme["accent"]
    bg = theme["bg"]
    trs = []
    for r_idx, cells in enumerate(rows):
        is_header = r_idx == 0 and len(rows) > 1
        tcs = []
        for c in cells:
            shd = f'<w:shd w:val="clear" w:color="auto" w:fill="{accent if is_header else (bg if r_idx % 2 == 1 else "FFFFFF")}"/>'
            color = "FFFFFF" if is_header else "1E293B"
            bold = "<w:b/>" if is_header else ""
            tcs.append(
                f"<w:tc><w:tcPr><w:tcW w:w=\"4500\" w:type=\"dxa\"/>{shd}</w:tcPr>"
                f"<w:p><w:pPr><w:spacing w:before=\"60\" w:after=\"60\"/></w:pPr>"
                f"<w:r><w:rPr><w:rFonts w:ascii=\"{font}\" w:hAnsi=\"{font}\"/>{bold}"
                f"<w:color w:val=\"{color}\"/><w:sz w:val=\"20\"/></w:rPr>"
                f"<w:t>{escape(c.strip())}</w:t></w:r></w:p></w:tc>"
            )
        trs.append(f"<w:tr>{''.join(tcs)}</w:tr>")
    return (
        f"<w:tbl><w:tblPr><w:tblW w:w=\"5000\" w:type=\"pct\"/>"
        f"<w:tblBorders>"
        f"<w:top w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"{accent}\"/>"
        f"<w:bottom w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"{accent}\"/>"
        f"<w:left w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"{accent}\"/>"
        f"<w:right w:val=\"single\" w:sz=\"6\" w:space=\"0\" w:color=\"{accent}\"/>"
        f"<w:insideH w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"CBD5E1\"/>"
        f"<w:insideV w:val=\"single\" w:sz=\"4\" w:space=\"0\" w:color=\"CBD5E1\"/>"
        f"</w:tblBorders></w:tblPr>{''.join(trs)}</w:tbl>"
    )


def zbuduj_docx_bytes(akapity: list[str], theme: dict[str, str]) -> bytes:
    """Create a styled .docx file in memory from paragraphs and a visual theme."""
    body_parts: list[str] = []
    table_buf: list[list[str]] = []

    for idx, p in enumerate(akapity):
        if " | " in p:
            table_buf.append([c.strip() for c in p.split(" | ")])
            continue
        if table_buf:
            body_parts.append(_xml_table(table_buf, theme))
            table_buf = []
        body_parts.append(_xml_paragraph(p, theme, idx))
    if table_buf:
        body_parts.append(_xml_table(table_buf, theme))

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(body_parts)}"
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/></w:sectPr>'
        "</w:body></w:document>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml.encode("utf-8"))
    return buf.getvalue()


def generuj_wszystkie() -> list[Path]:
    DOCX_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for row in db.wiersze_repozytorium():
        fn = row["file_name"]
        theme = motyw_dla(fn)
        akapity = akapity_dla_wiersza(row)
        out_path = sciezka_docx(fn)
        out_path.write_bytes(zbuduj_docx_bytes(akapity, theme))
        written.append(out_path)
    return written


if __name__ == "__main__":
    paths = generuj_wszystkie()
    print(f"Wygenerowano {len(paths)} plików .docx w {DOCX_DIR}")
