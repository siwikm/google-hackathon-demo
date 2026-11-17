from pathlib import Path
from typing import List
from pydantic import BaseModel, Field
from google.adk.agents import LlmAgent
from google.adk.tools import ToolContext
import dotenv

import pandas as pd

dotenv.load_dotenv()
# 1. Definicja ustrukturyzowanego formatu wyjściowego (Pydantic)
# To wymusi na modelu Gemini zwrot dokładnej tabeli ryzyk zgodnej z naszym schematem.


class ElementAnalizy(BaseModel):
    kategoria: str = Field(
        description="Kategoria: Kary Umowne, SLA, RODO, Wypowiedzenie lub Inne"
    )
    status_ryzyka: str = Field(
        description="Klasyfikacja: ZIELONY (zgodny), ZOLTY (umiarkowane ryzyko), CZERWONY (niezgodny / wysokie ryzyko)"
    )
    cytat_z_umowy: str = Field(
        description="Dokładny cytat lub fragment z analizowanej umowy odnoszący się do tej kategorii"
    )
    uzasadnienie_i_ryzyko: str = Field(
        description="Zwięzłe uzasadnienie decyzji biznesowej i opis zidentyfikowanego ryzyka"
    )
    proponowana_korekta: str = Field(
        description="Gotowa propozycja nowego brzmienia paragrafu zgodna ze standardem Grupy Pelion"
    )


class RaportCompliance(BaseModel):
    status_ogolny: str = Field(description="ZGODNY, WYMAGA_ZMIAN, lub RYZYKO_KRYTYCZNE")
    analiza_szczegolowa: List[ElementAnalizy] = Field(
        description="Lista zweryfikowanych klauzul i wymagań"
    )
    podsumowanie_menedzerskie: str = Field(
        description="Krótkie (2-3 zdania) podsumowanie dla zarządu z informacją o kluczowych ryzykach"
    )


# 2. Narzędzie w Pythonie (Tool) wczytujące naszą listę kontrolną z CSV
def pobierz_liste_kontrolna(tool_context: ToolContext) -> dict:
    """Pobiera oficjalną listę kontrolną wymagań i klauzul prawnych Grupy Pelion.
    Używaj ZAWSZE na początku procesu analizy umowy, aby poznać obowiązujące kryteria oceny.
    """
    try:
        df = pd.read_csv(Path(__file__).parent / "lista_kontrolna.csv")
        slownik_wymagan = df.to_dict(orient="records")
        # Zapisujemy w stanie sesji, by inne komponenty miały dostęp
        tool_context.state["lista_kontrolna"] = slownik_wymagan
        return {"lista_kontrolna": slownik_wymagan}
    except Exception as e:
        return {"error": f"Nie udało się załadować listy kontrolnej: {str(e)}"}


# 3. Definicja Głównego Agenta LCAI (LoopAgent / Autor-Weryfikator)
root_agent = LlmAgent(
    name="lcai_legal_compliance_agent",
    model="gemini-4-argon",  # Rekomendowany model do zaawansowanej analizy dokumentów prawnych
    description="Agent wspierający weryfikację umów i analizę zgodności (Compliance) dla Grupy Pelion.",
    instruction="""Jesteś doświadczonym radcą prawnym oraz ekspertem ds. compliance w Grupie Pelion.
    Twoim zadaniem jest zweryfikować załączoną umowę pod kątem zgodności z procedurami i wymaganiami.

    Wykonaj zadanie w następujących krokach:
    1. ZAWSZE zacznij od wywołania narzędzia `pobierz_liste_kontrolna`, aby zapoznać się z aktualnymi wymogami.
    2. Odczytaj treść przesłanej umowy (załącznika PDF/DOCX).
    3. Przeprowadź analizę punkt po punkcie: porównaj zapisy umowy z każdym wymogiem z listy kontrolnej.
    4. Dla każdej kategorii określ status ryzyka:
       - ZIELONY: Umowa w pełni spełnia wymóg z listy kontrolnej.
       - ZOLTY: Umowa reguluje kwestię, ale w sposób mało precyzyjny lub lekko odbiegający od standardu.
       - CZERWONY: Brak wymaganej klauzuli lub zapisy są bezpośrednio sprzeczne z listą kontrolną.
    5. Sformułuj konkretne rekomendacje i propozycje poprawek (proponowana_korekta) dla każdego wykrytego ryzyka.
    6. Zwróć ustrukturyzowany raport końcowy ściśle według schematu RaportCompliance.""",
    tools=[pobierz_liste_kontrolna],
    output_schema=RaportCompliance,
    output_key="raport_koncowy",
)
