# LCAI — prezentacja (5 min z live demo)

Plan czasu: slajdy 1–3 ok. 1,5 min · live demo ok. 3 min · slajd 4 ok. 30 s.

---

## Slajd 1. Problem

- Weryfikacja umowy przez dział prawny trwa dni, a nie minuty
- Każdą umowę trzeba ręcznie porównać z zasadami Grupy Pelion
- Kontrahenta sprawdza się osobno: biała lista VAT i lista sankcyjna
- Brak jednego miejsca, w którym widać odstępstwa we wszystkich umowach

## Slajd 2. Rozwiązanie: LCAI (Legal & Compliance AI)

**Weryfikacja umów w minutę, nie w tydzień**

- **Analiza umowy:** uwagi przy konkretnych akapitach i score ryzyka 0–100
- **Weryfikacja kontrahenta:** biała lista VAT (MF) i lista sankcyjna (MSWiA)
- **Rejestr umów:** pytania w języku naturalnym, odpowiedzi z BigQuery
- **Zasady:** 20 zasad dla umów B2B, DPA i NDA, progi zielony / żółty / czerwony

## Slajd 3. Narzędzia

- **Google ADK:** dwa agenty, analiza umowy i rejestr umów
- **Gemini na Vertex AI:** czyta umowę i odpowiada w ustalonym formacie (JSON)
- **BigQuery:** rejestr 40 umów; agent ma tylko prawo odczytu
- **API MF:** biała lista VAT, z cache i trybem offline
- **Lista sankcyjna MSWiA:** dopasowanie nazw kontrahentów i treści umowy
- **FastAPI + własny frontend:** podgląd dokumentu z ryzykami przy akapitach
- **Claude Code:** wsparcie przy pisaniu kodu i projektowaniu UI

Zasada działania: model czyta i interpretuje zapisy, a score, VAT i sankcje liczy kod, więc te wyniki są powtarzalne.

---

## Live demo (ok. 3 min)

1. **Analiza umowy:** przykład `b2b_przykład_yellow` → uruchomienie analizy
   - kroki agenta na żywo: zasady → VAT → sankcje
   - wynik: score 60, ryzyko WYSOKIE, 5 żółtych uwag (IP, zakaz konkurencji, odbiór, RODO, antykorupcja)
   - kliknięcie w uwagę pokazuje akapit w dokumencie
2. **Rejestr umów:** gotowe pytanie, np. „Które umowy zostały zatwierdzone (APPROVED) mimo czerwonych odstępstw?”
   - pokazanie wygenerowanego SQL i podświetlonych umów w tabeli
3. **Zasady:** filtr B2B, karta zasady z progami i punktami

Plan awaryjny: przy wolnej odpowiedzi Gemini pokazać przykład `b2b_przykład_green` (score 0) albo przygotowany wcześniej zrzut ekranu wyniku.

---

## Slajd 4. Efekt i dalsze kroki

**Efekt:**
- Analiza umowy w minutę: lista ryzyk przy akapitach i score 0–100
- Sprawdzenie kontrahenta (VAT, sankcje) w tym samym kroku
- Pytania o cały portfel umów bez pisania SQL

**Dalsze kroki:**
- Logowanie i role użytkowników (obecnie wersja demonstracyjna)
- Edycja zasad przez dział prawny (obecnie mockup)
- Integracja z obiegiem dokumentów i KSeF
