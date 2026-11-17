"""Scenario 2: search the contract registry for deviations from the group's rules, as an ADK Workflow.

    przygotowanie_pytania → wyszukiwanie_w_rejestrze → pobranie_umow

The model turns a question into SQL (own tool on SQLite, or ADK's BigQueryToolset when
REJESTR_BACKEND=bigquery) and/or uses the deterministic rule check. It returns only file names;
the last node loads the full rows and their deviations, so the table is never hallucinated.
"""

import json
import logging

from google.adk.agents import LlmAgent
from google.adk.agents.context import Context
from google.adk.tools import ToolContext
from google.adk.workflow import START, Workflow
from pydantic import BaseModel, Field

from core import config, rejestr
from core.zasady import ZASADY, odstepstwa

log = logging.getLogger(__name__)


class WynikWyszukiwania(BaseModel):
    odpowiedz: str = Field(description="2-4 zdania po polsku: co znaleziono i dlaczego to odstępstwo")
    sql: str | None = Field(default=None, description="ostatnie zapytanie SQL, które dało wynik (jeśli było)")
    file_names: list[str] = Field(description="file_name umów, które odpowiadają na pytanie")


def schemat_rejestru() -> dict:
    """Zwraca schemat tabeli rejestru umów (kolumny, typy, opisy) i zasady Grupy Pelion z progami."""
    return {**rejestr.schemat(), "zasady": ZASADY}


def wykonaj_sql(zapytanie: str, tool_context: ToolContext) -> dict:
    """Wykonuje pojedyncze zapytanie SELECT na rejestrze umów (tylko odczyt, max 200 wierszy).

    Args:
        zapytanie: zapytanie SQL (SQLite), np. SELECT file_name, contractor FROM umowy WHERE typ = 'DPA'.
    """
    tool_context.state["ostatni_sql"] = zapytanie
    try:
        rows = rejestr.wykonaj_select(zapytanie)
    except Exception as e:  # bad SQL goes back to the model so it can fix the query
        return {"blad": str(e)}
    return {"liczba": len(rows), "wiersze": rows}


def znajdz_odstepstwa(
    typ: str | None = None, tylko_czerwone: bool = False, status: str | None = None
) -> dict:
    """Ocenia każdą umowę z rejestru względem zasad Grupy Pelion i zwraca te z odstępstwami.

    Args:
        typ: B2B, DPA albo null (wszystkie).
        tylko_czerwone: True = tylko umowy z co najmniej jednym CZERWONYM odstępstwem.
        status: np. APPROVED, żeby znaleźć umowy zatwierdzone mimo odstępstw; null = dowolny.
    """
    out = []
    for row in rejestr.wszystkie(typ):
        if status and row.get("status") != status:
            continue
        devs = odstepstwa(row)
        if tylko_czerwone:
            devs = [d for d in devs if d["poziom"] == "CZERWONY"]
        if devs:
            out.append(
                {
                    "file_name": row["file_name"],
                    "contractor": row["contractor"],
                    "status": row["status"],
                    "odstepstwa": devs,
                }
            )
    return {"liczba": len(out), "umowy": out}


def _narzedzia() -> list:
    tools: list = [schemat_rejestru, znajdz_odstepstwa]
    if rejestr.backend() != "bigquery":
        return [*tools, wykonaj_sql]
    import google.auth
    from google.adk.integrations.bigquery import BigQueryCredentialsConfig, BigQueryToolset
    from google.adk.integrations.bigquery.config import BigQueryToolConfig, WriteMode

    credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return [
        *tools,
        BigQueryToolset(
            tool_filter=["execute_sql", "get_table_info"],
            credentials_config=BigQueryCredentialsConfig(credentials=credentials),
            bigquery_tool_config=BigQueryToolConfig(
                write_mode=WriteMode.BLOCKED,
                location=config.BQ_LOCATION,
                application_name="google-hackathon-demo",
            ),
        ),
    ]


def przygotowanie_pytania(ctx: Context) -> str:
    """Clears the previous run's SQL and result, and passes the question on."""
    ctx.state["ostatni_sql"] = None
    ctx.state["wynik"] = None
    content = ctx.user_content
    return "\n".join(p.text for p in (content.parts if content else []) if p.text)


def pobranie_umow(ctx: Context, node_input: dict | str | None) -> dict | None:
    """Loads the full rows and their deviations for the file names the model picked."""
    state = ctx.state
    wynik = json.loads(node_input) if isinstance(node_input, str) else dict(node_input or {})
    if not wynik:
        return None
    try:
        umowy = rejestr.z_odstepstwami(rejestr.pobierz(wynik.get("file_names") or []))
    except Exception as e:
        log.exception("Odczyt rejestru nie powiódł się")
        umowy, wynik["odpowiedz"] = [], f"{wynik.get('odpowiedz', '')} (Błąd odczytu rejestru: {e})"
    state["wynik"] = {
        "odpowiedz": wynik.get("odpowiedz"),
        "sql": wynik.get("sql") or state.get("ostatni_sql"),
        "umowy": umowy,
        "backend": rejestr.backend(),
        "tabela": rejestr.tabela(),
    }
    # compact node output for the Dev UI; the full result is state["wynik"]
    return {"umowy": len(umowy), "backend": rejestr.backend()}


SQL_HINT = (
    f"Dla BigQuery używaj narzędzia execute_sql z project_id='{config.BQ_PROJECT}' i tabeli {rejestr.tabela()}."
    if rejestr.backend() == "bigquery"
    else "Do zapytań używaj `wykonaj_sql` (SQLite, tabela `umowy`)."
)

wyszukiwanie_w_rejestrze = LlmAgent(
    name="wyszukiwanie_w_rejestrze",
    model=config.MODEL,
    generate_content_config=config.model_config(),
    description="Wyszukiwanie w rejestrze umów odstępstw od zasad Grupy Pelion (pytania w języku naturalnym).",
    instruction=f"""Jesteś analitykiem compliance Grupy Pelion i przeszukujesz rejestr wcześniej przeprocesowanych umów.

1. Zawsze zacznij od `schemat_rejestru` (kolumny + zasady z progami).
2. Pytanie o konkretny wymiar (np. brak zapisu o termination_data_policy, zgłoszenie naruszeń > 24 h) => napisz SQL. {SQL_HINT}
   - „bez zapisu o termination_data_policy” / „bez obowiązku usunięcia danych” => typ = 'DPA' AND usuwanie_danych = 0.
   - „termin płatności powyżej 30 dni” => typ = 'B2B' AND payment_term_days > 30.
   - „bez waloryzacji stawek” => typ = 'B2B' AND rate_indexation = 'None'; „bez trybu awaryjnego KSeF” => typ = 'B2B' AND ksef_emergency_mode = 'None'.
3. Pytanie ogólne o odstępstwa od zasad (np. „zatwierdzone mimo odstępstw”) => `znajdz_odstepstwa`.
4. W `file_names` zwróć tylko umowy, które faktycznie odpowiadają na pytanie. W `sql` podaj zapytanie, które dało wynik.
5. W `odpowiedz` krótko wyjaśnij, które zasady są naruszone (podaj wartości, np. 600 h zamiast max 24 h).""",
    tools=_narzedzia(),
    output_schema=WynikWyszukiwania,
    output_key="wynik_llm",
)

root_agent = Workflow(
    name="rejestr_umow",
    description="Wyszukiwanie w rejestrze umów odstępstw od zasad Grupy Pelion (pytania w języku naturalnym).",
    edges=[(START, przygotowanie_pytania, wyszukiwanie_w_rejestrze, pobranie_umow)],
)
