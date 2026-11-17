"""BigQuery contract registry (default backend; SQLite stays as the local fallback).

uv run python -m core.bq --seed     # create dataset + table, load the repository contracts
"""

import argparse
from contextlib import closing
from datetime import date, datetime
from typing import Any

from google.cloud import bigquery

from . import config, db
from .zasady import ZASADY


def _client() -> bigquery.Client:
    return bigquery.Client(project=config.BQ_PROJECT, location=config.BQ_LOCATION)


def _table_id(name: str = "umowy") -> str:
    return f"{config.BQ_PROJECT}.{config.BQ_DATASET}.{name}"


def _schema() -> list[bigquery.SchemaField]:
    return [
        bigquery.SchemaField(
            name, bq_type, mode="REQUIRED" if name == "file_name" else "NULLABLE", description=opis
        )
        for name, _, bq_type, opis in db.KOLUMNY
    ]


ZASADY_SCHEMA = [
    bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("typ", "STRING"),
    bigquery.SchemaField("kategoria", "STRING"),
    bigquery.SchemaField("krytycznosc", "STRING"),
    bigquery.SchemaField("wymaganie", "STRING"),
    bigquery.SchemaField("zielony", "STRING"),
    bigquery.SchemaField("zolty", "STRING"),
    bigquery.SchemaField("czerwony", "STRING"),
    bigquery.SchemaField("rekomendacja", "STRING"),
]

SANKCJE_SCHEMA = [
    bigquery.SchemaField("id", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("rodzaj", "STRING"),
    bigquery.SchemaField("nazwa", "STRING"),
    bigquery.SchemaField("dane", "STRING"),
    bigquery.SchemaField("uzasadnienie", "STRING"),
    bigquery.SchemaField("srodki", "STRING"),
    bigquery.SchemaField("data_wpisu", "STRING"),
    bigquery.SchemaField("data_wykreslenia", "STRING"),
    bigquery.SchemaField("tokeny", "STRING"),
]

VAT_CACHE_SCHEMA = [
    bigquery.SchemaField("nip", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("data", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("odpowiedz", "STRING"),
    bigquery.SchemaField("pobrano", "STRING"),
]


def _wiersze_vat_cache() -> list[dict[str, Any]]:
    db.upewnij_sie()
    with closing(db.polacz(readonly=True)) as conn:
        rows = {(r["nip"], r["data"]): dict(r) for r in conn.execute("SELECT * FROM vat_cache")}
    for p in config.VAT_CACHE_DIR.glob("*.json"):
        nip = p.stem
        if not any(k[0] == nip for k in rows):
            dzien = date.today().isoformat()
            rows[(nip, dzien)] = {
                "nip": nip,
                "data": dzien,
                "odpowiedz": p.read_text(encoding="utf-8"),
                "pobrano": datetime.now().isoformat(),
            }
    return list(rows.values())


def _load(client: bigquery.Client, table: str, rows: list[dict[str, Any]], schema: list[bigquery.SchemaField]) -> int:
    tid = _table_id(table)
    job = client.load_table_from_json(
        rows,
        tid,
        job_config=bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_TRUNCATE"),
    )
    job.result()
    return client.get_table(tid).num_rows


def seed() -> dict[str, int]:
    client = _client()
    dataset = bigquery.Dataset(f"{config.BQ_PROJECT}.{config.BQ_DATASET}")
    dataset.location = config.BQ_LOCATION
    client.create_dataset(dataset, exists_ok=True)

    umowy_rows = db.wiersze_repozytorium()
    backup_rows = db.wiersze_stare_repozytorium()
    sankcje_rows = [{"id": i, **r} for i, r in enumerate(db.wiersze_sankcji(), start=1)]
    zasady_rows = [{f.name: z.get(f.name) for f in ZASADY_SCHEMA} for z in ZASADY]
    vat_rows = _wiersze_vat_cache()

    return {
        "umowy": _load(client, "umowy", umowy_rows, _schema()),
        "umowy_backup": _load(client, "umowy_backup", backup_rows, _schema()),
        "zasady": _load(client, "zasady", zasady_rows, ZASADY_SCHEMA),
        "sankcje": _load(client, "sankcje", sankcje_rows, SANKCJE_SCHEMA),
        "vat_cache": _load(client, "vat_cache", vat_rows, VAT_CACHE_SCHEMA),
    }


_schemat_sprawdzony = False


def _dodaj_brakujace_kolumny(client: bigquery.Client) -> None:
    """Columns added to db.KOLUMNY after the table was seeded become new NULLABLE columns (once per process)."""
    global _schemat_sprawdzony
    if _schemat_sprawdzony:
        return
    table = client.get_table(_table_id())
    have = {f.name for f in table.schema}
    missing = [f for f in _schema() if f.name not in have]
    if missing:
        table.schema = [*table.schema, *missing]
        client.update_table(table, ["schema"])
    _schemat_sprawdzony = True


def zapisz_wiersz(row: dict[str, Any]) -> None:
    """Upsert one analysed contract (MERGE, so re-analysing the same file does not duplicate it)."""
    client = _client()
    _dodaj_brakujace_kolumny(client)
    names = db.NAZWY_KOLUMN
    params = [bigquery.ScalarQueryParameter(n, bq_type, row.get(n)) for n, _, bq_type, _ in db.KOLUMNY]
    source = ", ".join(f"@{n} AS {n}" for n in names)
    sets = ", ".join(f"{n} = S.{n}" for n in names if n != "file_name")
    sql = (
        f"MERGE `{_table_id()}` T USING (SELECT {source}) S ON T.file_name = S.file_name "
        f"WHEN MATCHED THEN UPDATE SET {sets} "
        f"WHEN NOT MATCHED THEN INSERT ({', '.join(names)}) VALUES ({', '.join('S.' + n for n in names)})"
    )
    client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="store_true")
    if parser.parse_args().seed:
        print(f"{config.BQ_PROJECT}.{config.BQ_DATASET}: {seed()}")
