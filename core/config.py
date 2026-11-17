"""Paths and settings. Importing this module loads the project's .env."""

import os
from pathlib import Path

import dotenv

ROOT = Path(__file__).resolve().parent.parent
dotenv.load_dotenv(ROOT / ".env")

WIEDZA = ROOT / "wiedza"
DEMO_DIR = WIEDZA / "demo"
VAT_CACHE_DIR = WIEDZA / "vat_cache"
DATA_DIR = ROOT / "data"
DB_PATH = Path(os.getenv("REJESTR_DB", DATA_DIR / "rejestr.db"))

SANKCJE_XLSX = WIEDZA / "tabela_lista_sankcyjna_03_11_2026.xlsx"
EXPANDED_REPO_JSON = WIEDZA / "expanded_contracts_database.json"
REPOZYTORIUM_JSON = {
    "B2B": WIEDZA / "snippet_B2B_repository_POCepruf.json",
    "DPA": WIEDZA / "snippet_UmPowDanych_repository_POCepruf.json",
}

MODEL = os.getenv("GEMINI_MODEL", "gemini-4-argon")
BQ_PROJECT = os.getenv("BQ_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", ""))
# Registry backend: bigquery (default) | sqlite. Without a GCP project there is no BigQuery to talk to,
# so a bare checkout falls back to the local SQLite copy (the UI shows which backend is in use).
REJESTR_BACKEND = (os.getenv("REJESTR_BACKEND") or ("bigquery" if BQ_PROJECT else "sqlite")).lower()
BQ_DATASET = os.getenv("BQ_DATASET", "rejestr_umow")
BQ_LOCATION = os.getenv("BQ_LOCATION", "EU")

# Our own company: never the counterparty in VAT checks.
NIP_WLASNY = {"9471958279"}

# Vertex sometimes stalls on a single request; cap each model call and retry transient errors.
GEMINI_TIMEOUT_MS = int(os.getenv("GEMINI_TIMEOUT_MS", "90000"))


def model_config():
    from google.genai import types

    return types.GenerateContentConfig(
        temperature=0.2,
        http_options=types.HttpOptions(
            timeout=GEMINI_TIMEOUT_MS,
            retry_options=types.HttpRetryOptions(
                attempts=3, initial_delay=1.0, max_delay=8.0, http_status_codes=[408, 429, 500, 502, 503, 504]
            ),
        ),
    )
