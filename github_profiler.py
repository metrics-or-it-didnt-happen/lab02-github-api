#!/usr/bin/env python3
"""GitHub Profiler - repository health analysis via GitHub API."""

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Counter
from dotenv import load_dotenv
import requests

GITHUB_API = "https://api.github.com"


def get_headers() -> dict:
    """Return auth headers for GitHub API."""


    load_dotenv()
    token = os.environ["GITHUB_TOKEN"]
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
    closed, open = 0, 0
    labels = Counter() 
    avarage_response_time = 0
    answered =0
    r = requests.get(f"{GITHUB_API}/repos/{owner_repo}/issues?state=all&sort=created&direction=desc&per_page=100", headers=headers)
    issues = r.json()
    issues_filtered = []
    for issue in issues:
        if 'pull_request' in issue:
            continue
        if 'state' not in issue:
            ValueError('Issue has no state')
        if issue['state'] == 'open':
            open+=1
        if issue['state'] == 'closed':
            closed+=1
        if 'labels' in issue:
            for label in issue['labels']:
                if 'name' in label:
                    labels[label['name']]+=1

        issues_filtered.append(issue)
        if closed + open <= 20:
            comments = requests.get(f"{issue['comments_url']}?per_page=1",headers=headers).json()
            if len(comments)==0:
                continue
            comment = comments[0]
            firts_response_time = datetime.fromisoformat(comment['created_at'].replace("Z", "+00:00"))
            issue_creation_time = datetime.fromisoformat(issue['created_at'].replace("Z", "+00:00"))
            delta = (firts_response_time - issue_creation_time).total_seconds() / 86400
            avarage_response_time += delta
            answered+=1
    issue_stat={'avarage_response_time': round(avarage_response_time/answered,1), 'closed': round(closed/(open+closed)*100), 'labels': dict(labels.most_common(5))}
    return issue_stat
            


def analyze_pull_requests(owner_repo: str, headers: dict,
                          count: int = 50) -> dict:
    """Analyze recent pull requests: merge time, merge rate."""
    # TODO: Twój kod tutaj
    # Endpoint: GET /repos/{owner}/{repo}/pulls
    # Parametry: state=all, sort=created, direction=desc, per_page=50
    r = requests.get(f"{GITHUB_API}/repos/{owner_repo}/pulls?state=all&sort=created&direction=desc&per_page=50", headers=headers).json()

    accpted, rejected, open = 0 , 0,0
    avarage_response_time=0
    for pr in r:
        if pr['state']=='open':
            open+=1
        elif pr['state']=='closed' and not pr['merged_at']:
            rejected+=1
        elif  pr['state']=='closed' and pr['merged_at'] is not None:
            accpted += 1
            merget_at = datetime.fromisoformat(pr['merged_at'].replace("Z", "+00:00"))
            created_at = datetime.fromisoformat(pr['created_at'].replace("Z", "+00:00"))
            delta = (merget_at - created_at).total_seconds() / 86400
            avarage_response_time += delta
        
    pr_stat ={'merged':round(accpted/(accpted+rejected+open)*100), 'rejected':round(100*rejected/(accpted+rejected+open)), 'open':round(100*open/(accpted+rejected+open)), 'avg_time':round(avarage_response_time/accpted,1)}
    return pr_stat


def analyze_activity(owner_repo: str, headers: dict) -> dict:
    """Compare recent activity with a year ago."""
    # TODO: Twój kod tutaj
    # Endpoint: GET /repos/{owner}/{repo}/commits
    # Użyj parametrów since= i until= z datami ISO 8601
    now = datetime.today()
    month_ago = now - timedelta(30)
    _11month_ago = now - timedelta(330)
    year_ago = now - timedelta(360)
    
    r = requests.get(f"{GITHUB_API}/repos/{owner_repo}/commits?since={now.isoformat().replace("+00:00","Z")}&untill={month_ago.isoformat().replace("+00:00","Z")}", headers=headers).json()
    r1 = requests.get(f"{GITHUB_API}/repos/{owner_repo}/commits?since={_11month_ago.isoformat().replace("+00:00","Z")}&untill={year_ago.isoformat().replace("+00:00","Z")}", headers=headers).json()
    
    c = requests.get(f"{GITHUB_API}/repos/{owner_repo}/collaborators?rel=\"last\"", headers=headers).json()
    activity_stat = {'now':len(r), 'year_ago':len(r1), 'trend': -round((len(r)/len(r1) - 1)*100)}
    return activity_stat
    


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
#     --- Issues (ostatnie 100) ---
#   Zamknięte:                   78%
#   Średni czas do odpowiedzi:   2.3 dni
#   Top etykiety:                bug (23), enhancement (15), question (12)
    print('--- Issues (ostatnie 100) ---')
    print(f"  Zamknięte:                  {issues['closed']}")
    print(f"  Średni czas do odpowiedzi:  {issues['avarage_response_time']}")
    print(f"  Top etykiety:              ")
    i = 0
    for key in issues['labels']:
        print(key,issues['labels'][key],end=', ')
    print()
#     --- Pull Requests (ostatnie 50) ---
#   Zmergowane:                  62%
#   Odrzucone:                   24%
#   Otwarte:                     14%
#   Średni czas do merge:        4.1 dni
    print('     --- Pull Requests (ostatnie 50) ---  ')
    print(f'   Zmergowane:                  {prs['merged']}%')
    print(f'   Odrzucone:                   {prs['rejected']}%')
    print(f'   Otwarte:                     {prs['open']}%')
    print(f'   Średni czas do merge:        {prs['avg_time']} dni')
# --- Aktywność ---
#   Commitów (ostatni miesiąc):  15
#   Commitów (rok temu):         23
#   Trend:                       spadek o 35%
    print(" --- Aktywność ---")
    print(f"   Commitów (ostatni miesiąc):  {activity['now']}")
    print(f'   Commitów (rok temu):         {activity['year_ago']}')
    print(f'   Trend:                       spadek o {activity['trend']}%')
    return


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