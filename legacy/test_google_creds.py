import os
import dotenv
from google.oauth2 import service_account
from google.cloud import discoveryengine_v1beta as discoveryengine
dotenv.load_dotenv()
# =====================================================================
# KONFIGURACJA TESTU
# =====================================================================
PATH_TO_JSON = "cepd-hackathon-group-06-021c845cbfb9.json"          # Nazwa Twojego pliku JSON z kluczem
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID")          # Podmień na swoje Project ID
GCP_DATA_STORE_ID = os.getenv("GCP_DATA_STORE_ID")    # Podmień na swoje Data Store ID
GCP_LOCATION = "europe-central2"                      # Domyślnie "global"

def test_gemini_notebook_access():
    print("🚦 Rozpoczynam test uprawnień dla konta usługi...")
    
    # 1. Sprawdzenie czy plik JSON istnieje
    if not os.path.exists(PATH_TO_JSON):
        print(f"❌ Błąd: Nie znaleziono pliku {PATH_TO_JSON} w tym katalogu!")
        return

    try:
        # 2. Ładowanie poświadczeń z pliku JSON
        credentials = service_account.Credentials.from_service_account_file(PATH_TO_JSON)
        print(f"✅ Pomyślnie załadowano klucz dla: {credentials.service_account_email}")
        
        # 3. Inicjalizacja klienta API
        client = discoveryengine.SearchServiceClient(credentials=credentials)
        
        serving_config = client.serving_config_path(
            project=GCP_PROJECT_ID,
            location=GCP_LOCATION,
            data_store=GCP_DATA_STORE_ID,
            serving_config="default_serving_config"
        )
        
        # 4. Próba wykonania minimalnego zapytania (test połączenia)
        print("🔗 Próba nawiązania połączenia z Gemini Notebook API...")
        request = discoveryengine.SearchRequest(
            serving_config=serving_config,
            query="test",
            page_size=1
        )
        
        # Wywołanie API
        response = client.search(request)
        
        print("\n🎉 SUKCES! Połączenie i uprawnienia działają prawidłowo!")
        print(f"Otrzymano odpowiedź z API. Liczba wyników wyszukiwania dla testu: {len(response.results)}")
        
    except Exception as e:
        print("\n❌ BŁĄD UPRAWNIEŃ LUB KONFIGURACJI!")
        error_msg = str(e)
        print(f"Szczegóły błędu: {error_msg}")
        
        if "PermissionDenied" in error_msg or "403" in error_msg:
            print("\n💡 Rozwiązanie:")
            print("Twoje konto usługi nie ma jeszcze przypisanej roli w IAM.")
            print("Idź do: https://console.cloud.google.com/iam-admin/iam")
            print(f"Dodaj do konta '{credentials.service_account_email}' rolę:")
            print("👉 'Discovery Engine Viewer' (Przeglądający silnik Discovery Engine)")
        elif "NotFoundError" in error_msg or "404" in error_msg:
            print("\n💡 Rozwiązanie:")
            print("API zwraca błąd 404. Sprawdź dokładnie, czy GCP_PROJECT_ID oraz GCP_DATA_STORE_ID są poprawne.")

if __name__ == "__main__":
    test_gemini_notebook_access()
