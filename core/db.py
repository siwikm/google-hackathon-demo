"""Local SQLite store: contract registry, rules, sanctions list, VAT cache.

uv run python -m core.db --seed
"""

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import date
from typing import Any

import openpyxl

from . import config
from .tekst import tokeny
from .zasady import BRAK_ZAPISU, ZASADY, usuwanie_danych

# (column, SQLite type, BigQuery type, description shown to the agent)
KOLUMNY: list[tuple[str, str, str, str]] = [
    ("file_name", "TEXT PRIMARY KEY", "STRING", "nazwa pliku umowy (identyfikator)"),
    ("typ", "TEXT", "STRING", "B2B albo DPA (umowa powierzenia przetwarzania danych)"),
    ("contractor", "TEXT", "STRING", "kontrahent"),
    ("nip", "TEXT", "STRING", "NIP kontrahenta (jeśli znany)"),
    ("status", "TEXT", "STRING", "APPROVED, APPROVED_WITH_RESERVATION, NOWA_ANALIZA"),
    ("sign_date", "TEXT", "STRING", "data podpisania YYYY-MM-DD"),
    ("signoff_date", "TEXT", "STRING", "data akceptacji (sign-off) YYYY-MM-DD"),
    (
        "zrodlo",
        "TEXT",
        "STRING",
        "repozytorium (wcześniej przeprocesowane) albo analiza (dodane z aplikacji)",
    ),
    ("score", "INTEGER", "INT64", "score ryzyka 0-100 z analizy (NULL dla repozytorium)"),
    ("services_scope", "TEXT", "STRING", "B2B: zakres usług"),
    ("ip_transfer_moment", "TEXT", "STRING", "B2B: moment przeniesienia praw autorskich"),
    ("non_compete_months", "INTEGER", "INT64", "B2B: zakaz konkurencji w miesiącach"),
    ("max_penalties_percent", "REAL", "FLOAT64", "B2B: limit kar umownych w % wynagrodzenia"),
    ("governing_law", "TEXT", "STRING", "B2B: prawo właściwe"),
    ("jurisdiction", "TEXT", "STRING", "B2B: sąd właściwy"),
    (
        "payment_term_days",
        "INTEGER",
        "INT64",
        "B2B: termin płatności faktury w dniach (NULL = brak terminu albo brak danych)",
    ),
    (
        "rate_indexation",
        "TEXT",
        "STRING",
        "B2B: klauzula waloryzacji stawek ('None' = brak zapisu, NULL = brak danych)",
    ),
    (
        "ksef_emergency_mode",
        "TEXT",
        "STRING",
        "B2B: faktury przy niedostępności/awarii KSeF ('None' = brak zapisu, NULL = brak danych)",
    ),
    ("sub_processing_rules", "TEXT", "STRING", "DPA: zasady dalszego powierzenia"),
    ("breach_notification_hours", "INTEGER", "INT64", "DPA: termin zgłoszenia naruszenia w godzinach"),
    ("audit_rights", "TEXT", "STRING", "DPA: prawo audytu"),
    ("termination_data_policy", "TEXT", "STRING", "DPA: co dzieje się z danymi po zakończeniu umowy"),
    (
        "usuwanie_danych",
        "INTEGER",
        "INT64",
        "DPA: 1 = umowa zobowiązuje do usunięcia/zwrotu danych, 0 = brak zapisu albo 'No deletion'",
    ),
    ("liability_limit_pln", "REAL", "FLOAT64", "DPA: limit odpowiedzialności w PLN"),
    ("duration", "TEXT", "STRING", "czas trwania umowy (np. Czas nieokreślony, Czas określony do YYYY-MM-DD)"),
    ("purpose", "TEXT", "STRING", "NDA: cel udostępnienia informacji poufnych"),
    ("protection_period_years", "INTEGER", "INT64", "NDA: okres ochrony poufności w latach"),
    ("permitted_recipients", "TEXT", "STRING", "NDA: uprawnieni odbiorcy informacji poufnych"),
    ("contractual_penalty_pln", "REAL", "FLOAT64", "NDA: kara umowna za naruszenie poufności w PLN"),
    ("data_dodania", "TEXT", "STRING", "data dodania do rejestru"),
]
NAZWY_KOLUMN = [k[0] for k in KOLUMNY]
TYPY_BQ = {k[0]: k[2] for k in KOLUMNY}

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS umowy ({", ".join(f"{name} {kind}" for name, kind, _, _ in KOLUMNY)});
CREATE TABLE IF NOT EXISTS umowy_backup ({", ".join(f"{name} {kind}" for name, kind, _, _ in KOLUMNY)});
CREATE TABLE IF NOT EXISTS zasady (id TEXT PRIMARY KEY, typ TEXT, kategoria TEXT, krytycznosc TEXT,
    wymaganie TEXT, zielony TEXT, zolty TEXT, czerwony TEXT);
CREATE TABLE IF NOT EXISTS sankcje (id INTEGER PRIMARY KEY, rodzaj TEXT, nazwa TEXT, dane TEXT,
    uzasadnienie TEXT, srodki TEXT, data_wpisu TEXT, data_wykreslenia TEXT, tokeny TEXT);
CREATE TABLE IF NOT EXISTS vat_cache (nip TEXT, data TEXT, odpowiedz TEXT, pobrano TEXT, PRIMARY KEY (nip, data));
"""


INSERT_ZASADY = (
    "INSERT INTO zasady VALUES (:id, :typ, :kategoria, :krytycznosc, :wymaganie, :zielony, :zolty, :czerwony)"
)


def polacz(readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    else:
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _cast_val(name: str, val: Any) -> Any:
    if val is None or val == "":
        return None
    bq_type = TYPY_BQ.get(name)
    if bq_type == "INT64":
        return int(float(val))
    if bq_type == "FLOAT64":
        return float(val)
    return str(val)


def wiersz_umowy(record: dict[str, Any], typ: str | None = None, zrodlo: str | None = None) -> dict[str, Any]:
    """Registry row from a repository JSON record or an analysis' dimensions."""
    row = {name: _cast_val(name, record.get(name)) for name in NAZWY_KOLUMN}
    row["typ"] = typ or row.get("typ")
    row["zrodlo"] = zrodlo or row.get("zrodlo") or "repozytorium"
    row["signoff_date"] = row.get("signoff_date") or row.get("sign_date") or date.today().isoformat()
    row["data_dodania"] = row.get("data_dodania") or date.today().isoformat()
    if row["typ"] == "DPA":
        row["usuwanie_danych"] = int(usuwanie_danych(record.get("termination_data_policy")))
    if row["typ"] == "B2B" and row["zrodlo"] == "analiza":
        # the analysis looked for these clauses: a missing one is stored as 'None', NULL stays "not known"
        for name in ("rate_indexation", "ksef_emergency_mode"):
            row[name] = row.get(name) or BRAK_ZAPISU
    return row


def wiersze_stare_repozytorium() -> list[dict[str, Any]]:
    rows = []
    for typ, path in config.REPOZYTORIUM_JSON.items():
        for record in json.loads(path.read_text(encoding="utf-8")):
            rows.append(wiersz_umowy(record, typ, "repozytorium"))
    return rows


def wiersze_repozytorium() -> list[dict[str, Any]]:
    if config.EXPANDED_REPO_JSON.exists():
        return [
            wiersz_umowy(record, record.get("typ"), record.get("zrodlo") or "repozytorium")
            for record in json.loads(config.EXPANDED_REPO_JSON.read_text(encoding="utf-8"))
        ]
    return wiersze_stare_repozytorium()


def wiersze_sankcji() -> list[dict[str, Any]]:
    wb = openpyxl.load_workbook(config.SANKCJE_XLSX, read_only=True, data_only=True)
    rows = []
    for sheet, rodzaj in (("osoby", "osoba"), ("podmioty", "podmiot")):
        for r in list(wb[sheet].iter_rows(values_only=True))[1:]:
            if not r[0]:
                continue
            fmt = lambda v: v.date().isoformat() if hasattr(v, "date") else (str(v).strip() if v else None)  # noqa: E731
            rows.append(
                {
                    "rodzaj": rodzaj,
                    "nazwa": str(r[0]).strip(),
                    "dane": fmt(r[1]),
                    "uzasadnienie": fmt(r[2]),
                    "srodki": fmt(r[3]),
                    "data_wpisu": fmt(r[4]),
                    "data_wykreslenia": fmt(r[5]),
                    "tokeny": " ".join(tokeny(str(r[0]))),
                }
            )
    return rows


def zapisz_umowe_sqlite(row: dict[str, Any]) -> None:
    cols = ", ".join(NAZWY_KOLUMN)
    marks = ", ".join("?" for _ in NAZWY_KOLUMN)
    with closing(polacz()) as conn, conn:
        conn.execute(
            f"INSERT OR REPLACE INTO umowy ({cols}) VALUES ({marks})", [row.get(c) for c in NAZWY_KOLUMN]
        )


def seed() -> dict[str, int]:
    """Rebuild umowy, umowy_backup, zasady and sankcje from wiedza/. Keeps the VAT cache."""
    with closing(polacz()) as conn, conn:
        conn.executescript(
            "DROP TABLE IF EXISTS umowy; DROP TABLE IF EXISTS umowy_backup; DROP TABLE IF EXISTS zasady; DROP TABLE IF EXISTS sankcje;"
        )
        conn.executescript(SCHEMA)
        for row in wiersze_repozytorium():
            conn.execute(
                f"INSERT INTO umowy ({', '.join(NAZWY_KOLUMN)}) VALUES ({', '.join('?' for _ in NAZWY_KOLUMN)})",
                [row.get(c) for c in NAZWY_KOLUMN],
            )
        for row in wiersze_stare_repozytorium():
            conn.execute(
                f"INSERT INTO umowy_backup ({', '.join(NAZWY_KOLUMN)}) VALUES ({', '.join('?' for _ in NAZWY_KOLUMN)})",
                [row.get(c) for c in NAZWY_KOLUMN],
            )
        conn.executemany(INSERT_ZASADY, ZASADY)
        conn.executemany(
            "INSERT INTO sankcje (rodzaj, nazwa, dane, uzasadnienie, srodki, data_wpisu, data_wykreslenia, tokeny) "
            "VALUES (:rodzaj, :nazwa, :dane, :uzasadnienie, :srodki, :data_wpisu, :data_wykreslenia, :tokeny)",
            wiersze_sankcji(),
        )
        counts = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in ("umowy", "umowy_backup", "zasady", "sankcje")
        }
    return counts


def upewnij_sie() -> None:
    """Seed on first use, so a fresh checkout (or container) works without a manual step."""
    if not config.DB_PATH.exists():
        seed()
        return
    with closing(polacz()) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not {"umowy", "zasady", "sankcje", "vat_cache"} <= tables:
        seed()
        return
    with closing(polacz()) as conn, conn:
        # Columns added after the database was created: add them in place, keeping analysed contracts.
        have = {r[1] for r in conn.execute("PRAGMA table_info(umowy)")}
        for name, kind, _, _ in KOLUMNY:
            if name not in have:
                conn.execute(f"ALTER TABLE umowy ADD COLUMN {name} {kind}")
        # The rules table is a copy of ZASADY; keep it in step with the code.
        conn.execute("DELETE FROM zasady")
        conn.executemany(INSERT_ZASADY, ZASADY)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true", help="przebuduj bazę z plików w wiedza/")
    args = parser.parse_args()
    if args.seed:
        print(seed())
    else:
        upewnij_sie()
        with closing(polacz(readonly=True)) as conn:
            for t in ("umowy", "zasady", "sankcje", "vat_cache"):
                print(t, conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
