"""Web app: ADK API server (agents under agents/) + the demo frontend.

    uv run uvicorn server:app --port 8001
    open http://127.0.0.1:8001          # frontend
    open http://127.0.0.1:8001/dev-ui/  # ADK Dev UI (same agents)

The frontend talks to the agents only through ADK endpoints (/apps/.../sessions, /run_sse).
The /api/* routes here are helpers that never call the model: text extraction for the preview,
sample files, the registry table.
"""

from pathlib import Path

from fastapi import File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.routing import APIRoute
from google.adk.cli.fast_api import get_fast_api_app

from core import config, db, generator_docx, rejestr, scoring
from core.struktura import struktura
from core.tekst import akapity_z_bajtow, tekst_dla_agenta
from core.zasady import NIE_DOTYCZY, ZASADY, metoda_oceny

STATIC = config.ROOT / "static"
MAX_FILE_BYTES = 15 * 1024 * 1024
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PRZYKLADY = [
    config.DEMO_DIR / "umowa_demo_b2b.txt",
    config.DEMO_DIR / "umowa_demo_b2b.docx",
    *sorted(config.WIEDZA.glob("*_przykład_*.txt")),
    *sorted(config.WIEDZA.glob("NDA_*.docx")),
]

db.upewnij_sie()
generator_docx.generuj_wszystkie()
app = get_fast_api_app(agents_dir=str(config.ROOT / "agents"), web=True, use_local_storage=False)
# ADK's dev UI redirects "/" to /dev-ui/; the demo frontend takes "/" instead.
app.router.routes = [r for r in app.router.routes if not (isinstance(r, APIRoute) and r.path == "/")]


def _akapity(name: str, data: bytes) -> dict:
    try:
        akapity = akapity_z_bajtow(name, data)
    except ValueError as e:
        raise HTTPException(415, str(e)) from e
    except Exception as e:  # broken DOCX/zip
        raise HTTPException(400, f"Nie udało się odczytać pliku: {e}") from e
    if not akapity:
        raise HTTPException(400, "Plik nie zawiera tekstu.")
    return {
        "nazwa": name,
        "motyw": generator_docx.motyw_dla(name),
        "akapity": akapity,
        "bloki": struktura(akapity),
        "tekst": tekst_dla_agenta(akapity),
    }


def _upewnij_docx(nazwa: str) -> Path:
    path = generator_docx.sciezka_docx(Path(nazwa).name)
    if not path.exists():
        rows = rejestr.pobierz([Path(nazwa).name])
        if not rows:
            raise HTTPException(404, "Nie znaleziono takiej umowy.")
        theme = generator_docx.motyw_dla(nazwa)
        akapity = generator_docx.akapity_dla_wiersza(rows[0])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(generator_docx.zbuduj_docx_bytes(akapity, theme))
    return path


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/przyklady")
def przyklady() -> list[str]:
    return [p.name for p in PRZYKLADY if p.exists()]


@app.get("/api/przyklady/{nazwa}")
def przyklad(nazwa: str) -> dict:
    path = next((p for p in PRZYKLADY if p.name == nazwa and p.exists()), None)
    if path is None:
        raise HTTPException(404, "Nie ma takiego przykładu.")
    return _akapity(path.name, path.read_bytes())


@app.post("/api/tekst")
async def tekst(plik: UploadFile = File(...)) -> dict:
    data = await plik.read()
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "Plik jest za duży (limit 15 MB).")
    return _akapity(Path(plik.filename or "umowa.txt").name, data)


@app.get("/api/umowy/{nazwa}/docx")
def pobierz_umowe_docx(nazwa: str) -> FileResponse:
    path = _upewnij_docx(nazwa)
    return FileResponse(path, media_type=DOCX_MIME, filename=path.name)


@app.get("/api/umowy/{nazwa}")
def podglad_umowy(nazwa: str) -> dict:
    path = _upewnij_docx(nazwa)
    return _akapity(Path(nazwa).name, path.read_bytes())


@app.get("/api/rejestr")
def rejestr_umow() -> dict:
    try:
        umowy = [
            {**u, "motyw": generator_docx.motyw_dla(u["file_name"])}
            for u in rejestr.z_odstepstwami(rejestr.wszystkie())
        ]
    except Exception as e:
        raise HTTPException(502, f"Rejestr niedostępny ({rejestr.backend()}): {e}") from e
    return {"backend": rejestr.backend(), "tabela": rejestr.tabela(), "umowy": umowy}


@app.get("/api/zasady")
def zasady() -> list[dict]:
    """Rules plus how each is checked, what it costs in the score and where it does not apply."""
    return [
        {
            **z,
            "metoda": metoda_oceny(z["id"]),
            "punkty": {p: scoring.punkty(z, p) for p in ("ZOLTY", "CZERWONY")},
            "nie_dotyczy": list(NIE_DOTYCZY.get(z["id"], ())),
        }
        for z in ZASADY
    ]
