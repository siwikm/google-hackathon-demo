# Przykłady komunikacji frontend ↔ serwer ADK

Dokument pokazuje rzeczywiste żądania i odpowiedzi HTTP wymieniane między frontendem ([static/index.html](../static/index.html)) a serwerem API Google ADK podczas analizy umowy i wyszukiwania w rejestrze. Dane pochodzą z przebiegu z 2026-11-17 (Google ADK 2.14.0, agenty jako grafy `Workflow`, rejestr SQLite na serwerze testowym). Długie pola skrócono znakiem `…`, a pola nieistotne dla frontendu (np. `thoughtSignature`, szczegóły `usageMetadata`) pominięto.

Architektura, sekwencje i podział odpowiedzialności model ↔ kod są opisane w [architektura-komunikacji.md](architektura-komunikacji.md).

## Spis treści

1. [Przegląd](#1-przegląd)
2. [Analiza umowy krok po kroku](#2-analiza-umowy-krok-po-kroku)
3. [Strumień SSE: zdarzenia analizy](#3-strumień-sse-zdarzenia-analizy)
4. [Odczyt wyniku](#4-odczyt-wyniku)
5. [Rejestr umów](#5-rejestr-umów)
6. [Podgląd na żywo w przeglądarce](#6-podgląd-na-żywo-w-przeglądarce)

## 1. Przegląd

Frontend i ADK Dev UI (`/dev-ui/`) to dwaj niezależni klienci tego samego serwera API ADK. Oba działają w jednym procesie uvicorn ([server.py](../server.py)) pod tym samym adresem, więc nie ma CORS ani osobnej konfiguracji.

Jedno uruchomienie agenta to zawsze trzy żądania wysyłane przez funkcję `runAgent` ([static/index.html:578](../static/index.html#L578)):

| Krok | Żądanie | Do czego frontend używa odpowiedzi |
| --- | --- | --- |
| 1 | `POST /apps/{app}/users/demo/sessions` | `id` nowej sesji |
| 2 | `POST /run_sse` | strumień zdarzeń, wyłącznie do listy kroków „na żywo” |
| 3 | `GET /apps/{app}/users/demo/sessions/{id}` | `state.wynik`, czyli wynik końcowy |

Przed analizą frontend pobiera tekst umowy z endpointu pomocniczego `/api/*`, który nie korzysta z ADK ani z modelu.

## 2. Analiza umowy krok po kroku

### 2.0. Przygotowanie tekstu (bez ADK, bez modelu)

```http
GET /api/przyklady/umowa_demo_b2b.txt
```

```json
{
  "nazwa": "umowa_demo_b2b.txt",
  "akapity": ["UMOWA O ŚWIADCZENIE USŁUG B2B nr 47/KSEF/2026", "Zawarta w dniu 16 listopada 2026 r. w Łodzi pomiędzy:", "…"],
  "bloki": ["…"],
  "tekst": "[P1] UMOWA O ŚWIADCZENIE USŁUG B2B nr 47/KSEF/2026\n[P2] Zawarta w dniu 16 listopada 2026 r. w Łodzi pomiędzy:\n…"
}
```

Pole `tekst` (akapity ponumerowane `[Pn]`) trafia potem do agenta. Dla pliku wgranego z dysku ten sam format zwraca `POST /api/tekst`.

### 2.1. Utworzenie sesji

```http
POST /apps/analiza_umowy/users/demo/sessions
Content-Type: application/json

{"state": {"nazwa_pliku": "umowa_demo_b2b.txt"}}
```

```json
{
  "id": "a62ae856-e817-47de-96d8-3b0ff3e8ac5f",
  "appName": "analiza_umowy",
  "userId": "demo",
  "state": {"nazwa_pliku": "umowa_demo_b2b.txt"},
  "events": [],
  "lastUpdateTime": 1794919617.4
}
```

- `app_name` w ścieżce to nazwa katalogu w [agents/](../agents/); agenta wybiera zakładka UI, nie model.
- `user_id` jest zawsze `demo`. Każde kliknięcie tworzy nową sesję, więc agent nie pamięta poprzednich analiz.
- Stan początkowy przekazuje parametry wywołania: analiza podaje `nazwa_pliku` (klucz zapisu w rejestrze), rejestr wysyła pusty stan.

### 2.2. Uruchomienie agenta

```http
POST /run_sse
Content-Type: application/json
Accept: text/event-stream

{
  "app_name": "analiza_umowy",
  "user_id": "demo",
  "session_id": "a62ae856-e817-47de-96d8-3b0ff3e8ac5f",
  "streaming": false,
  "new_message": {
    "role": "user",
    "parts": [{"text": "[P1] UMOWA O ŚWIADCZENIE USŁUG B2B nr 47/KSEF/2026\n[P2] …"}]
  }
}
```

Pozostałe pola modelu żądania ADK (`RunAgentRequest`: `state_delta`, `invocation_id`, `function_call_event_id`, `custom_metadata`, `service_tier`) frontend pomija.

Odpowiedź ma typ `text/event-stream`: każde zdarzenie to jedna linia `data: {JSON}` zakończona pustą linią. Pola JSON są w camelCase. `streaming: false` oznacza, że transport to nadal SSE, ale każde zdarzenie jest kompletne (bez fragmentów tokenów). Frontend czyta strumień przez `fetch` i `ReadableStream`, bo `EventSource` nie obsługuje metody POST.

## 3. Strumień SSE: zdarzenia analizy

Opisywany przebieg wysłał 9 zdarzeń. Każde zdarzenie ma `id`, `invocationId`, `author`, `timestamp`, `nodeInfo.path` (węzeł grafu, który je wysłał) i `actions.stateDelta` (zmiany w stanie sesji). Zdarzenie kończące węzeł ma pole `output`.

### Zdarzenie 1: węzeł `przygotowanie` (funkcja)

```json
data: {
  "author": "analiza_umowy",
  "nodeInfo": {"path": "analiza_umowy@1/przygotowanie@1"},
  "actions": {"stateDelta": {
    "akapity": ["UMOWA O ŚWIADCZENIE USŁUG B2B nr 47/KSEF/2026", "…"],
    "ekstrakcja": null, "ocena_klauzul": null, "wynik": null
  }},
  "output": "[P1] UMOWA O ŚWIADCZENIE USŁUG B2B nr 47/KSEF/2026\n[P2] …"
}
```

Frontend: brak reakcji.

### Zdarzenie 2: węzeł `klasyfikacja_i_ekstrakcja` (Gemini)

```json
data: {
  "author": "klasyfikacja_i_ekstrakcja",
  "modelVersion": "gemini-4-argon",
  "finishReason": "STOP",
  "nodeInfo": {"path": "analiza_umowy@1/klasyfikacja_i_ekstrakcja@1"},
  "content": {"role": "model", "parts": [{"text": "{\n  \"typ_umowy\": \"B2B\", …"}]},
  "usageMetadata": {"promptTokenCount": 3610, "candidatesTokenCount": 1681, "totalTokenCount": 5291},
  "actions": {"stateDelta": {"ekstrakcja": {"…": "to samo co output"}}},
  "output": {
    "typ_umowy": "B2B",
    "tytul": "UMOWA O ŚWIADCZENIE USŁUG B2B nr 47/KSEF/2026",
    "strony": [
      {"rola": "Zleceniodawca", "nazwa": "epruf S.A.", "nip": "9471958279"},
      {"rola": "Zleceniobiorca", "nazwa": "MINISTERSTWO FINANSÓW", "nip": "5260250274"},
      "…"
    ],
    "osoby": ["Paweł Świątek", "Błażej Reiss"],
    "platnosc": {"kwota": "45 000 PLN netto miesięcznie", "rachunek": "PL 50 1140 2004 0000 3102 7865 4321", "akapit": 15, "…": "…"},
    "kluczowe_zapisy": ["…"],
    "wymiary": {"…": "…"}
  }
}
```

Frontend rozpoznaje zdarzenie po `nodeInfo.path`. Wiersz „Gemini czyta umowę” dostaje tekst „typ umowy: B2B · strony: 5” i pojawiają się wiersze „Wykaz podatników VAT MF” oraz „Lista sankcyjna MSWiA”.

### Zdarzenie 3: węzeł `weryfikator_vat` (funkcja, gałąź równoległa)

```json
data: {
  "author": "analiza_umowy",
  "branch": "weryfikator_vat@1",
  "nodeInfo": {"path": "analiza_umowy@1/weryfikator_vat@1"},
  "output": {
    "nip": "5260250274",
    "znaleziony": true,
    "nazwa": "MINISTERSTWO FINANSÓW",
    "status_vat": "Czynny",
    "liczba_rachunkow_w_wykazie": 17,
    "rachunki": [{"rachunek": "PL 50 1140 2004 0000 3102 7865 4321", "nrb": "50114020040000310278654321", "na_liscie": false}],
    "data_sprawdzenia": "2026-11-17",
    "zrodlo": "cache"
  }
}
```

Frontend: wiersz VAT zamknięty jako „MINISTERSTWO FINANSÓW · Czynny · rachunek spoza wykazu” (czerwony). Gdy w umowie nie ma NIP-u kontrahenta, `output` to `{"nip": null, "blad": "brak NIP kontrahenta w umowie"}`.

### Zdarzenie 4: węzeł `weryfikator_sankcji` (funkcja, gałąź równoległa)

```json
data: {
  "author": "analiza_umowy",
  "branch": "weryfikator_sankcji@1",
  "nodeInfo": {"path": "analiza_umowy@1/weryfikator_sankcji@1"},
  "output": {
    "sprawdzono_nazw": 6,
    "wpisow_na_liscie": 553,
    "trafienia": [{
      "nazwa_na_liscie": "REISS Błażej Bernard",
      "rodzaj": "osoba",
      "dopasowanie": "nazwa",
      "zapytanie": "Błażej Reiss",
      "data_wpisu": "2024-09-13"
    }]
  }
}
```

Frontend: wiersz sankcji zamknięty jako „trafienie: REISS Błażej Bernard” (czerwony).

### Zdarzenie 5: `audytor_klauzul` wywołuje narzędzie

```json
data: {
  "author": "audytor_klauzul",
  "nodeInfo": {"path": "analiza_umowy@1/audytor_klauzul@1"},
  "content": {"role": "model", "parts": [{"functionCall": {
    "id": "call_1636510478838439758",
    "name": "pobierz_zasady",
    "args": {"typ_umowy": "B2B"}
  }}]}
}
```

Frontend: nowy wiersz „Zasady Grupy Pelion · typ umowy: B2B”.

### Zdarzenie 6: odpowiedź narzędzia

```json
data: {
  "author": "audytor_klauzul",
  "content": {"role": "user", "parts": [{"functionResponse": {
    "id": "call_1636510478838439758",
    "name": "pobierz_zasady",
    "response": {"zasady": [
      {"id": "B2B-IP", "kategoria": "Prawa autorskie", "zielony": "…", "zolty": "…", "czerwony": "…"},
      "… łącznie 13 zasad"
    ]}
  }}]},
  "actions": {"stateDelta": {"typ_umowy": "B2B"}}
}
```

Frontend: wiersz zasad zamknięty („13 zasad”) i nowy wiersz „Gemini porównuje zapisy z zasadami”.

### Zdarzenie 7: wynik audytora (Gemini)

```json
data: {
  "author": "audytor_klauzul",
  "nodeInfo": {"path": "analiza_umowy@1/audytor_klauzul@1"},
  "content": {"role": "model", "parts": [{"text": "{\n  \"ryzyka\": [ … ] }"}]},
  "actions": {"stateDelta": {"ocena_klauzul": {"…": "to samo co output"}}},
  "output": {
    "ryzyka": [
      {"zasada_id": "B2B-WALOR", "poziom": "ZOLTY", "opis": "Umowa nie zawiera postanowień dotyczących waloryzacji…", "cytat": ""},
      "…"
    ],
    "zgodnosc": [
      {"zasada_id": "B2B-TERMIN", "akapit": 14, "uwaga": "termin płatności 14 dni"},
      "…"
    ]
  }
}
```

Gdy model nie potrafi oddać JSON-u natywnie przy włączonych narzędziach, ADK dokłada narzędzie `set_model_response` i wynik przychodzi jako jego `functionCall`. Frontend pomija ten krok na liście.

### Zdarzenie 8: węzeł `scalenie_wynikow` (JoinNode)

```json
data: {
  "nodeInfo": {"path": "analiza_umowy@1/scalenie_wynikow@1"},
  "output": {
    "weryfikator_vat": {"…": "…"},
    "weryfikator_sankcji": {"…": "…"},
    "audytor_klauzul": {"…": "…"}
  }
}
```

### Zdarzenie 9: węzeł `finalizacja_i_scoring` (funkcja)

```json
data: {
  "nodeInfo": {"path": "analiza_umowy@1/finalizacja_i_scoring@1"},
  "actions": {"stateDelta": {"wynik": {"…": "pełny wynik, patrz sekcja 4"}}},
  "output": {
    "score": {"wartosc": 100, "poziom": "KRYTYCZNE"},
    "ryzyka": 8,
    "zapis_rejestru": {"ok": true, "backend": "sqlite", "file_name": "umowa_demo_b2b.txt"}
  }
}
```

Po tym zdarzeniu serwer zamyka strumień.

### Błąd w trakcie działania agenta

Status HTTP pozostaje 200, bo nagłówki zostały już wysłane. ADK wysyła wtedy zdarzenie:

```json
data: {"error": "<Typ>: <komunikat>", "error_details": {"…": "…"}}
```

Frontend zamienia je na wyjątek ([static/index.html:599](../static/index.html#L599)) i pokazuje krok „Błąd” z przyciskiem ponowienia.

## 4. Odczyt wyniku

```http
GET /apps/analiza_umowy/users/demo/sessions/a62ae856-e817-47de-96d8-3b0ff3e8ac5f
```

```json
{
  "id": "a62ae856-e817-47de-96d8-3b0ff3e8ac5f",
  "appName": "analiza_umowy",
  "userId": "demo",
  "events": ["… te same 9 zdarzeń …"],
  "state": {
    "nazwa_pliku": "umowa_demo_b2b.txt",
    "akapity": ["…"],
    "ekstrakcja": {"…": "…"},
    "ocena_klauzul": {"…": "…"},
    "typ_umowy": "B2B",
    "wynik": {
      "typ_umowy": "B2B",
      "tytul": "UMOWA O ŚWIADCZENIE USŁUG B2B nr 47/KSEF/2026",
      "strony": ["…"],
      "osoby": ["…"],
      "podsumowanie": "Umowa B2B na czas nieokreślony…",
      "kluczowe_zapisy": ["…"],
      "platnosc": {"…": "…"},
      "wymiary": {"…": "…"},
      "ryzyka": [
        {
          "id": "R1",
          "kategoria": "Sankcje",
          "poziom": "CZERWONY",
          "zasada_id": "ALL-SANKCJE",
          "opis": "Podmiot z umowy figuruje na liście sankcyjnej MSWiA jako „REISS Błażej Bernard”…",
          "akapit": 24,
          "cytat": "Błażej Reiss",
          "rekomendacja": "Wstrzymać podpisanie umowy…",
          "dowod": {"zrodlo": "Lista sankcyjna MSWiA (03.11.2026)", "…": "…"}
        },
        "… R2 (ALL-VAT) … R8"
      ],
      "zgodnosc": ["…"],
      "zasady": {"typ": "B2B", "liczba": 11, "zgodne": 5},
      "score": {
        "wartosc": 100,
        "poziom": "KRYTYCZNE",
        "powod": "Trafienie na liście sankcyjnej MSWiA: współpraca niedopuszczalna.",
        "skladniki": ["…"]
      },
      "vat": {"nip": "5260250274", "status_vat": "Czynny", "nazwa": "MINISTERSTWO FINANSÓW", "rachunki": ["…"]},
      "sankcje": {"trafienia": [{"nazwa_na_liscie": "REISS Błażej Bernard", "…": "…"}], "wpisow_na_liscie": 553},
      "nazwa_pliku": "umowa_demo_b2b.txt",
      "zapis_rejestru": {"ok": true, "backend": "sqlite", "file_name": "umowa_demo_b2b.txt"}
    }
  }
}
```

Frontend czyta wyłącznie `state.wynik`. Na jego podstawie powstają werdykt, score, notatki na marginesie dokumentu i podświetlenia cytatów w akapitach `[Pn]`. Wynik pochodzi ze stanu sesji, a nie ze strumienia, bo buduje go kod ostatniego węzła, a nie odpowiedź modelu.

## 5. Rejestr umów

Schemat wymiany jest ten sam, różnią się agent i dane.

```http
POST /apps/rejestr_umow/users/demo/sessions
Content-Type: application/json

{"state": {}}
```

```http
POST /run_sse
Content-Type: application/json
Accept: text/event-stream

{
  "app_name": "rejestr_umow",
  "user_id": "demo",
  "session_id": "<id>",
  "streaming": false,
  "new_message": {"role": "user", "parts": [{"text": "Które umowy B2B mają termin płatności powyżej 14 dni?"}]}
}
```

Zdarzenia SSE w kolejności:

| Zdarzenie | Zawartość | Frontend |
| --- | --- | --- |
| `output` węzła `przygotowanie_pytania` | treść pytania | brak reakcji |
| `functionCall` `schemat_rejestru` | `{}` | wiersz „Schemat rejestru” |
| `functionResponse` `schemat_rejestru` | kolumny, zasady z progami, `backend` | „backend: sqlite” |
| `functionCall` `wykonaj_sql` | `{"zapytanie": "SELECT file_name, contractor, payment_term_days FROM umowy WHERE typ = 'B2B' AND payment_term_days > 14"}` | wiersz „Zapytanie SQL” |
| `functionResponse` `wykonaj_sql` | `{"liczba": 6, "wiersze": [ … ]}` | „6 wierszy” |
| `output` węzła `wyszukiwanie_w_rejestrze` | `{"odpowiedz": "…", "sql": "…", "file_names": [ … ]}` | brak reakcji |
| `output` węzła `pobranie_umow` | `{"umowy": 6, "backend": "sqlite"}` | brak reakcji |

Przy backendzie BigQuery zamiast `wykonaj_sql` przychodzą wywołania `execute_sql` (argument `query`) i ewentualnie `get_table_info` z `BigQueryToolset`.

Wynik w `GET /apps/rejestr_umow/users/demo/sessions/<id>`:

```json
"wynik": {
  "odpowiedz": "Znaleziono 6 umów B2B, w których termin płatności wynosi 30 dni, co przekracza dopuszczalny próg 14 dni…",
  "sql": "SELECT file_name, contractor, payment_term_days FROM umowy WHERE typ = 'B2B' AND payment_term_days > 14",
  "umowy": [
    {
      "file_name": "b2b_umowa_partner_16.txt",
      "contractor": "…",
      "status": "…",
      "odstepstwa": [{"zasada_id": "B2B-TERMIN", "poziom": "ZOLTY", "…": "…"}]
    },
    "…"
  ],
  "backend": "sqlite",
  "tabela": "umowy"
}
```

Model zwraca tylko nazwy plików (`file_names`). Pełne wiersze i ich odstępstwa ładuje z rejestru węzeł `pobranie_umow`, więc tabela w UI zawsze pokazuje dane z bazy.

## 6. Podgląd na żywo w przeglądarce

- **Frontend:** DevTools → Network → żądanie `run_sse` → zakładka EventStream (albo Response) pokazuje linie `data:` w kolejności nadejścia. Żądania `sessions` pokazują tworzenie i odczyt sesji.
- **ADK Dev UI** (`/dev-ui/`): po wybraniu aplikacji i użytkownika `demo` widać te same sesje i zdarzenia, wraz z grafem workflow i podświetloną ścieżką wykonania. Sesje są tylko w pamięci procesu, więc restart serwera je usuwa.
- **Terminal:** przykłady wywołań przez `curl` są w sekcji 11 [architektura-komunikacji.md](architektura-komunikacji.md#11-uruchomienie-i-diagnostyka).
