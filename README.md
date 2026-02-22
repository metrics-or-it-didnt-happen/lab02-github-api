# Lab 02: GitHub API — stalking z klasą

## Czy wiesz, że...

Według badań (które właśnie wymyśliłem), przeciętny developer sprawdza liczbę gwiazdek obcego repo zanim zdecyduje się go użyć, ale nigdy nie sprawdza liczbę otwartych issues. A potem się dziwi.

## Kontekst

W poprzednim labie kopaliśmy w historii gita lokalnie. Dziś idziemy dalej — sięgamy po dane, które żyją na serwerze GitHuba: issues, pull requesty, statystyki kontrybutorów, aktywność. GitHub udostępnia REST API, które pozwala odpytywać repozytoria programowo — bez klikania po interfejsie webowym.

W realnej pracy inżyniera umiejętność korzystania z API GitHuba przydaje się do: automatyzacji workflow (boty, CI/CD), analizy projektów OSS przed podjęciem decyzji o adopcji, monitorowania zdrowia własnych repozytoriów, albo po prostu zbierania danych do badań.

## Cel laboratorium

Po tym laboratorium będziesz potrafić:
- uwierzytelnić się w GitHub API za pomocą Personal Access Token,
- odpytywać REST API GitHuba (issues, pull requesty, contributors),
- radzić sobie z paginacją i rate limitingiem,
- napisać skrypt profilujący dowolne repozytorium na podstawie danych z API.

## Wymagania wstępne

- Python 3.9+ z biblioteką `requests` (lub `PyGithub`)
- Konto na GitHubie
- **Personal Access Token (PAT)** — instrukcja poniżej
- Podstawowa znajomość REST API (co to GET, JSON, status code)

### Jak uzyskać Personal Access Token

1. Wejdź na https://github.com/settings/tokens
2. Kliknij "Generate new token (classic)"
3. Nadaj nazwę (np. "ORKiPO lab")
4. Zaznacz scope: `public_repo` (wystarczy do czytania publicznych repozytoriów)
5. Kliknij "Generate token"
6. **Skopiuj token od razu** — nie zobaczysz go ponownie

**WAŻNE:** Nie commitujcie tokena do repozytorium! Używajcie zmiennej środowiskowej:

```bash
export GITHUB_TOKEN="ghp_twoj_token_tutaj"
```

## Zadania

### Zadanie 1: Rozgrzewka z API (30 min)

Zanim napiszemy skrypt, trzeba zrozumieć jak API działa. Zaczynamy od ręcznych zapytań.

**Krok 1:** Sprawdź czy token działa:

```bash
curl -H "Authorization: token $GITHUB_TOKEN" https://api.github.com/user
```

Powinieneś zobaczyć JSON z danymi swojego profilu.

**Krok 2:** Pobierz informacje o wybranym repo:

```bash
curl -H "Authorization: token $GITHUB_TOKEN" \
  https://api.github.com/repos/psf/requests
```

**Krok 3:** To samo w Pythonie:

```python
import os
import requests

token = os.environ["GITHUB_TOKEN"]
headers = {"Authorization": f"token {token}"}

response = requests.get(
    "https://api.github.com/repos/psf/requests",
    headers=headers,
)
repo = response.json()

print(f"Nazwa: {repo['full_name']}")
print(f"Gwiazdki: {repo['stargazers_count']}")
print(f"Forki: {repo['forks_count']}")
print(f"Otwarte issues: {repo['open_issues_count']}")
print(f"Język: {repo['language']}")
```

**Krok 4:** Sprawdź swój rate limit:

```python
r = requests.get("https://api.github.com/rate_limit", headers=headers)
limits = r.json()["rate"]
print(f"Limit: {limits['limit']}/h")
print(f"Pozostało: {limits['remaining']}")
print(f"Reset: {limits['reset']}")
```

Z tokenem masz 5000 zapytań na godzinę. Bez tokena — 60. Raczej wystarczy, ale lepiej nie odpytywać w pętli bez sensu.

### Zadanie 2: GitHub Profiler (60 min)

Napiszcie skrypt `github_profiler.py`, który dla podanego repozytorium generuje kompletny profil na podstawie danych z API.

**Co skrypt ma robić:**

Dla danego repo (np. `psf/requests`) pobrać i wyliczyć:

1. **Podstawowe metryki:** stars, forks, open issues, watchers, język, licencja
2. **Analiza issues (ostatnie 100):**
   - Średni czas do pierwszej odpowiedzi (komentarza)
   - Procent zamkniętych vs otwartych
   - Top 5 najczęstszych etykiet (labels)
3. **Analiza pull requestów (ostatnie 50):**
   - Średni czas do merge'a (od otwarcia do zamknięcia)
   - Procent zmergowanych vs odrzuconych vs otwartych
4. **Aktywność:**
   - Liczba commitów w ostatnim miesiącu
   - Liczba commitów rok temu w analogicznym miesiącu (dla porównania)
   - Liczba unikatowych kontrybutorów (ostatnia strona z API)

**Punkt startowy:**

```python
#!/usr/bin/env python3
"""GitHub Profiler - repository health analysis via GitHub API."""

import os
import sys
from datetime import datetime, timedelta, timezone

import requests

GITHUB_API = "https://api.github.com"


def get_headers() -> dict:
    """Return auth headers for GitHub API."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Ustaw zmienną GITHUB_TOKEN!")
        sys.exit(1)
    return {"Authorization": f"token {token}"}


def fetch_paginated(url: str, headers: dict, params: dict | None = None,
                    max_items: int = 100) -> list:
    """Fetch paginated results from GitHub API.

    GitHub API returns max 100 items per page. This function handles
    pagination via the 'Link' header.
    """
    items = []
    params = params or {}
    params.setdefault("per_page", min(max_items, 100))

    while url and len(items) < max_items:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        items.extend(response.json())
        params = {}  # params only for first request

        # Parse 'next' link from Link header
        link_header = response.headers.get("Link", "")
        url = None
        for part in link_header.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip(" <>")

    return items[:max_items]


def get_repo_info(owner_repo: str, headers: dict) -> dict:
    """Fetch basic repository information."""
    r = requests.get(f"{GITHUB_API}/repos/{owner_repo}", headers=headers)
    r.raise_for_status()
    return r.json()


def analyze_issues(owner_repo: str, headers: dict,
                   count: int = 100) -> dict:
    """Analyze recent issues: response time, close rate, top labels."""
    # TODO: Twój kod tutaj
    # Endpoint: GET /repos/{owner}/{repo}/issues
    # Parametry: state=all, sort=created, direction=desc, per_page=100
    # Uwaga: endpoint /issues zwraca też pull requesty!
    #   Filtruj: issue bez klucza "pull_request"
    pass


def analyze_pull_requests(owner_repo: str, headers: dict,
                          count: int = 50) -> dict:
    """Analyze recent pull requests: merge time, merge rate."""
    # TODO: Twój kod tutaj
    # Endpoint: GET /repos/{owner}/{repo}/pulls
    # Parametry: state=all, sort=created, direction=desc, per_page=50
    pass


def analyze_activity(owner_repo: str, headers: dict) -> dict:
    """Compare recent activity with a year ago."""
    # TODO: Twój kod tutaj
    # Endpoint: GET /repos/{owner}/{repo}/commits
    # Użyj parametrów since= i until= z datami ISO 8601
    pass


def print_report(repo_info: dict, issues: dict, prs: dict,
                 activity: dict) -> None:
    """Print formatted report to console."""
    print(f"\n{'=' * 60}")
    print(f"PROFIL REPOZYTORIUM: {repo_info['full_name']}")
    print(f"{'=' * 60}")

    print(f"\n--- Podstawowe metryki ---")
    print(f"  Gwiazdki:       {repo_info['stargazers_count']:,}")
    print(f"  Forki:          {repo_info['forks_count']:,}")
    print(f"  Otwarte issues: {repo_info['open_issues_count']:,}")
    print(f"  Język:          {repo_info.get('language', 'N/A')}")
    license_name = repo_info.get("license", {})
    print(f"  Licencja:       {license_name.get('spdx_id', 'N/A') if license_name else 'N/A'}")

    # TODO: wydrukuj sekcje issues, PRs, activity
    pass


def main():
    if len(sys.argv) < 2:
        print("Użycie: python github_profiler.py <owner/repo>")
        print("Przykład: python github_profiler.py psf/requests")
        sys.exit(1)

    owner_repo = sys.argv[1]
    headers = get_headers()

    print(f"Profiluję {owner_repo}...")

    repo_info = get_repo_info(owner_repo, headers)
    issues = analyze_issues(owner_repo, headers)
    prs = analyze_pull_requests(owner_repo, headers)
    activity = analyze_activity(owner_repo, headers)

    print_report(repo_info, issues, prs, activity)


if __name__ == "__main__":
    main()
```

**Oczekiwany output (przykład):**

```
Profiluję psf/requests...

============================================================
PROFIL REPOZYTORIUM: psf/requests
============================================================

--- Podstawowe metryki ---
  Gwiazdki:       52,300
  Forki:          9,200
  Otwarte issues: 120
  Język:          Python
  Licencja:       Apache-2.0

--- Issues (ostatnie 100) ---
  Zamknięte:                   78%
  Średni czas do odpowiedzi:   2.3 dni
  Top etykiety:                bug (23), enhancement (15), question (12)

--- Pull Requests (ostatnie 50) ---
  Zmergowane:                  62%
  Odrzucone:                   24%
  Otwarte:                     14%
  Średni czas do merge:        4.1 dni

--- Aktywność ---
  Commitów (ostatni miesiąc):  15
  Commitów (rok temu):         23
  Trend:                       spadek o 35%
```

### Zadanie 3: Porównywarka repozytoriów (45 min) — dla ambitnych

Rozszerzcie `github_profiler.py` (lub napiszcie oddzielny skrypt `compare_repos.py`) o tryb porównania dwóch repozytoriów.

**Do zrobienia:**
- Przyjmij dwa argumenty: `owner/repo1` i `owner/repo2`
- Wygeneruj tabelę porównawczą (side-by-side)
- Dodaj prosty "verdict": które repo wygląda zdrowiej i dlaczego

**Przykładowy output:**

```
PORÓWNANIE: psf/requests vs encode/httpx
============================================================
Metryka                  requests        httpx
------------------------------------------------------------
Gwiazdki                 52,300          13,400
Forki                    9,200           950
Otwarte issues           120             85
% zamkniętych issues     78%             82%
Śr. czas odpowiedzi     2.3 dni         1.1 dni
% zmergowanych PR        62%             71%
Śr. czas merge           4.1 dni         2.8 dni
Commitów (ost. miesiąc)  15              28

Verdict: httpx wygląda aktywniej i szybciej reaguje na issues.
```

## Co oddajecie

W swoim branchu `lab02_nazwisko1_nazwisko2`:

1. **`github_profiler.py`** — działający skrypt z zadania 2
2. **`report.txt`** — output skryptu dla wybranego repo (skopiowany z konsoli)
3. *(opcjonalnie)* **`compare_repos.py`** — porównywarka z zadania 3

**WAŻNE:** Nie commitujcie swojego tokena! Sprawdźcie `git diff` przed `git add`.

## Kryteria oceny

- Skrypt poprawnie się uwierzytelnia i obsługuje brak tokena
- Paginacja działa (nie gubicie danych przy > 30 itemach per page)
- Analiza issues poprawnie odfiltruje pull requesty z endpointu `/issues`
- Czasy odpowiedzi i merge'a są liczone poprawnie (w dniach)
- Output jest czytelny i zawiera wszystkie wymagane sekcje
- Token nie jest zahardkodowany w kodzie ani commitowany

## FAQ

**P: Mój token nie działa / dostaję 401.**
O: Sprawdź czy `echo $GITHUB_TOKEN` zwraca coś sensownego. Jeśli zamknąłeś terminal, musisz ponownie `export GITHUB_TOKEN=...`.

**P: Dostaję 403 / rate limit exceeded.**
O: Sprawdź `/rate_limit`. Z tokenem masz 5000 req/h — jeśli to przekroczyłeś, musisz poczekać do resetu. Bez tokena masz tylko 60.

**P: Endpoint `/issues` zwraca mi pull requesty!**
O: Tak, to znana cecha API GitHuba. Issue bez klucza `"pull_request"` to prawdziwy issue. Filtrujcie.

**P: Jak policzyć czas do pierwszej odpowiedzi na issue?**
O: Dla każdego issue pobierz komentarze (`/issues/{number}/comments`), weź datę pierwszego. Uwaga: to dodatkowe zapytanie per issue — rozważ ograniczenie do np. 20 issues.

**P: Mogę użyć biblioteki PyGithub zamiast requests?**
O: Tak, jak najbardziej. PyGithub opakowuje REST API i obsługuje paginację za Ciebie. Ale upewnij się, że rozumiesz co się dzieje pod spodem.

## Przydatne linki

- [GitHub REST API documentation](https://docs.github.com/en/rest)
- [GitHub API: Repositories](https://docs.github.com/en/rest/repos)
- [GitHub API: Issues](https://docs.github.com/en/rest/issues)
- [GitHub API: Pull Requests](https://docs.github.com/en/rest/pulls)
- [PyGithub documentation](https://pygithub.readthedocs.io/)
- [requests library](https://docs.python-requests.org/)

---
*"Jeśli nie możesz tego zmierzyć, nie możesz tym zarządzać."* — Peter Drucker (albo ktoś inny, nikt nie jest pewien)
