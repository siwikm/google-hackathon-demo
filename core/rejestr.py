"""Contract registry behind one interface: BigQuery (default) or local SQLite (REJESTR_BACKEND=sqlite)."""

import re
from contextlib import closing
from typing import Any

from . import config, db
from .zasady import odstepstwa

MAX_WIERSZY = 200
SELECT_RE = re.compile(r"^\s*(select|with)\b", re.I)


def backend() -> str:
    return "bigquery" if config.REJESTR_BACKEND == "bigquery" else "sqlite"


def tabela() -> str:
    """Fully qualified table name, as the agent should write it in SQL."""
    if backend() == "bigquery":
        return f"`{config.BQ_PROJECT}.{config.BQ_DATASET}.umowy`"
    return "umowy"


def schemat() -> dict[str, Any]:
    return {
        "backend": backend(),
        "tabela": tabela(),
        "kolumny": [
            {"nazwa": n, "typ": bq if backend() == "bigquery" else sq.split()[0], "opis": opis}
            for n, sq, bq, opis in db.KOLUMNY
        ],
        "uwagi": [
            "Typy umów: B2B (usługi) i DPA (umowa powierzenia przetwarzania danych).",
            "Kolumny B2B są NULL dla DPA i odwrotnie.",
            "Brak zapisu o usuwaniu danych po zakończeniu umowy: usuwanie_danych = 0 "
            "(obejmuje termination_data_policy = NULL, pusty tekst i 'No deletion').",
            "payment_term_days, rate_indexation i ksef_emergency_mode są wypełniane tylko przez analizę "
            "(zrodlo = 'analiza'). rate_indexation / ksef_emergency_mode = 'None' oznacza brak takiego zapisu "
            "w umowie; NULL oznacza brak danych (repozytorium albo starsza analiza), nie brak zapisu.",
            "Rejestr nie ma kolumn dla zasad NDA-*, B2B-ODBIOR, ALL-KSEF, ALL-RODO-KLAUZULA i ALL-KORUPCJA: "
            "są oceniane tylko w analizie pojedynczej umowy, a umowy NDA nie trafiają do rejestru.",
            "Tekstowe wymiary są po angielsku (np. 'General consent', 'Upon acceptance of monthly report'); "
            "do wyszukiwania tekstu używaj LOWER(kolumna) LIKE '%...%'.",
        ],
    }


def _sprawdz_select(sql: str) -> str:
    sql = sql.strip().rstrip(";").strip()
    if not SELECT_RE.match(sql) or ";" in sql:
        raise ValueError("Dozwolone jest tylko pojedyncze zapytanie SELECT.")
    return sql


def _bq_client():
    from google.cloud import bigquery

    return bigquery.Client(project=config.BQ_PROJECT, location=config.BQ_LOCATION)


def wykonaj_select(sql: str) -> list[dict[str, Any]]:
    sql = _sprawdz_select(sql)
    if backend() == "bigquery":
        rows = _bq_client().query(sql).result(max_results=MAX_WIERSZY)
        return [dict(r.items()) for r in rows]
    db.upewnij_sie()
    with closing(db.polacz(readonly=True)) as conn:
        return [dict(r) for r in conn.execute(sql).fetchmany(MAX_WIERSZY)]


def wszystkie(typ: str | None = None) -> list[dict[str, Any]]:
    sql = f"SELECT * FROM {tabela()}"
    if typ in ("B2B", "DPA", "NDA"):
        sql += f" WHERE typ = '{typ}'"
    return wykonaj_select(sql + " ORDER BY sign_date")


def pobierz(file_names: list[str]) -> list[dict[str, Any]]:
    wanted = set(file_names)
    return [r for r in wszystkie() if r["file_name"] in wanted]


def z_odstepstwami(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**r, "odstepstwa": odstepstwa(r)} for r in rows]


def zapisz(row: dict[str, Any]) -> None:
    if backend() == "bigquery":
        from .bq import zapisz_wiersz

        zapisz_wiersz(row)
    else:
        db.upewnij_sie()
        db.zapisz_umowe_sqlite(row)
