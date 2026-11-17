"""Prosty frontend do weryfikacji umów agentem ADK z agent.py.

    .venv/bin/uvicorn google_demo.main:app --reload --port 8001
    open http://127.0.0.1:8001

Each request runs root_agent in a fresh in-memory session and returns the
RaportCompliance the agent stores under its output_key. Nothing is persisted.
"""

import csv
import io
import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from google.adk.runners import InMemoryRunner
from google.genai import types

from .agent import RaportCompliance, root_agent

APP_NAME = "google_demo"
USER_ID = "frontend"
HERE = Path(__file__).parent
STATIC_DIR = HERE / "static"
CHECKLIST_CSV = HERE / "lista_kontrolna.csv"
MAX_FILE_BYTES = 15 * 1024 * 1024  # Gemini accepts ~20 MB of inline data per request
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
PROMPT = "Zweryfikuj poniższą umowę pod kątem zgodności z listą kontrolną Grupy Pelion."

runner = InMemoryRunner(agent=root_agent, app_name=APP_NAME)
app = FastAPI(title="Weryfikacja umów — LCAI")


def docx_text(data: bytes) -> str:
    """Paragraph text of a .docx file. Gemini reads PDF natively, but not DOCX."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        root = ElementTree.fromstring(archive.read("word/document.xml"))
    paragraphs = ("".join(t.text or "" for t in p.iter(f"{WORD_NS}t")) for p in root.iter(f"{WORD_NS}p"))
    return "\n".join(p for p in paragraphs if p.strip())


async def contract_parts(tekst: str, plik: UploadFile | None) -> list[types.Part]:
    """The user message for the agent: the instruction, the attached file and/or the pasted text."""
    parts = [types.Part.from_text(text=PROMPT)]
    if plik is not None and plik.filename:
        data = await plik.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, "Plik jest za duży (limit 15 MB).")
        name = plik.filename.lower()
        if name.endswith(".pdf"):
            parts.append(types.Part.from_bytes(data=data, mime_type="application/pdf"))
        elif name.endswith(".docx"):
            try:
                text = docx_text(data)
            except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as e:
                raise HTTPException(400, "Nie udało się odczytać pliku DOCX.") from e
            parts.append(types.Part.from_text(text=f"Treść załącznika {plik.filename}:\n\n{text}"))
        elif name.endswith((".txt", ".md")):
            parts.append(types.Part.from_text(text=data.decode("utf-8", errors="replace")))
        else:
            raise HTTPException(415, "Obsługiwane pliki: PDF, DOCX, TXT.")
    if tekst.strip():
        parts.append(types.Part.from_text(text=tekst.strip()))
    if len(parts) == 1:
        raise HTTPException(400, "Wklej treść umowy albo dodaj plik.")
    return parts


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/lista-kontrolna")
def lista_kontrolna() -> list[dict[str, str]]:
    """The checklist the agent verifies against (same CSV its tool reads)."""
    with CHECKLIST_CSV.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


@app.post("/api/weryfikuj")
async def weryfikuj(tekst: str = Form(""), plik: UploadFile | None = File(None)) -> dict:
    message = types.Content(role="user", parts=await contract_parts(tekst, plik))
    session = await runner.session_service.create_session(app_name=APP_NAME, user_id=USER_ID)
    try:
        async for _ in runner.run_async(user_id=USER_ID, session_id=session.id, new_message=message):
            pass
        done = await runner.session_service.get_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=session.id
        )
    except Exception as e:  # model/API errors: quota, auth, unknown model, blocked content
        raise HTTPException(502, f"Błąd agenta: {e}") from e
    finally:
        await runner.session_service.delete_session(app_name=APP_NAME, user_id=USER_ID, session_id=session.id)

    raport = done.state.get(root_agent.output_key) if done else None
    if isinstance(raport, str):
        raport = json.loads(raport)
    if not raport:
        raise HTTPException(502, "Agent nie zwrócił raportu.")
    return RaportCompliance.model_validate(raport).model_dump()
