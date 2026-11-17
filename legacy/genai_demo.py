# -*- coding: utf-8 -*-
# Nowe SDK `google-genai` (to samo, którego używa ADK). Stare `google-generativeai`
# wymusza protobuf<6 i psuje `adk eval`, dlatego nie należy go instalować w tym venv.
from google import genai
import dotenv

dotenv.load_dotenv()

# 1. Wklej swoj klucz z Google AI Studio (zaczyna sie od AIzaSy...)
API_KEY = dotenv.get_key(
    dotenv.find_dotenv(), "GEMINI_API_KEY"
)  # <--- WPISZ TUTAJ SWÓJ KLUCZ w pliku .env

try:
    print("🚀 Wysylam zapytanie testowe do Gemini przez klucz API (Google AI Studio)...")

    # 2. Klient z kluczem API; vertexai=False, bo .env ustawia GOOGLE_GENAI_USE_VERTEXAI=TRUE
    client = genai.Client(api_key=API_KEY, vertexai=False)

    # 3. Wygenerowanie odpowiedzi
    response = client.models.generate_content(
        model="gemini-4-argon",
        contents="Czesc! Potwierdz dzialanie polaczenia przez klucz API.",
    )

    print("\n🎉 SUKCES! Polaczenie z Gemini przez klucz API dziala prawidlowo:")
    print(response.text)

except Exception as e:
    print(f"\n❌ Wystapil blad: {e}")
