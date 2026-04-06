#!/usr/bin/env python3
"""GitHub Profiler - repository health analysis via GitHub API."""

import os
import sys
import re
from datetime import datetime, timedelta, timezone
from collections import Counter

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
    query_args = {
	'state': 'all',
	'sort': 'created',
	'direction': 'desc',
	'per_page': 100
    }
    r = requests.get(f"{GITHUB_API}/repos/{owner_repo}/issues", params=query_args, headers=headers)
    r.raise_for_status()
    all_data = r.json()
    issues_only = [issue for issue in all_data if 'pull_request' not in issue] 

    response_times = []
    for issue in [i for i in issues_only if i['comments'] > 0][:20]:
        res = requests.get(issue['comments_url'], params=query_args, headers=headers) 
        comments_data = res.json()
    
        if isinstance(comments_data, list) and len(comments_data) > 0:
            first_comm_date = datetime.fromisoformat(comments_data[0]['created_at'].replace('Z', '+00:00'))
            issue_created_date = datetime.fromisoformat(issue['created_at'].replace('Z', '+00:00'))
            response_times.append((first_comm_date - issue_created_date).total_seconds())

    average_response_time = sum(response_times) / len(response_times) if response_times else 0
    average_response_days = average_response_time / 86400

    closed_count = sum(1 for issue in issues_only if issue['state'] == 'closed')
    percent_closed = (closed_count / len(issues_only)) * 100 

    all_labels = []
    for issue in issues_only:
        for label in issue['labels']:
            all_labels.append(label['name'])

    label_counts = Counter(all_labels)
    top_5_labels = label_counts.most_common(5)

    # print(f" DEBUG: Liczba wszystkich issues: {len(issues_only)}")
    # Sprawdzamy, ile z nich ma przypięte JAKIEKOLWIEK etykiety
    # with_labels = sum(1 for i in issues_only if i['labels'])
    # print(f" DEBUG: Issues z etykietami: {with_labels}")

    return {
        'time_to_comment': round(average_response_days, 3),
        'percent_closed': round(percent_closed, 2),
        'common_labels': top_5_labels
    }


def analyze_pull_requests(owner_repo: str, headers: dict,
                          count: int = 50) -> dict:
    """Analyze recent pull requests: merge time, merge rate."""
    # TODO: Twój kod tutaj
    # Endpoint: GET /repos/{owner}/{repo}/pulls
    # Parametry: state=all, sort=created, direction=desc, per_page=50
    query_args = {
	'state': 'all',
	'sort': 'created',
	'direction': 'desc',
	'per_page': 50
    }
    r = requests.get(f"{GITHUB_API}/repos/{owner_repo}/pulls", params=query_args, headers=headers)
    r.raise_for_status()
    all_data = r.json()
    prs_only = all_data[:50]
    total_prs = len(prs_only)

    merged_count,rejected_count,open_count = 0,0,0
    merge_times = []

    for pr in prs_only:
        # 1. PR Otwarty
        if pr['state'] == 'open':
            open_count += 1
    
        # 2. PR Zmergowany (Sukces)
        elif pr.get('merged_at'):
            merged_count += 1
            start = datetime.fromisoformat(pr['created_at'].replace('Z', '+00:00'))
            end = datetime.fromisoformat(pr['merged_at'].replace('Z', '+00:00'))
            merge_times.append((end - start).total_seconds())
    
        # 3. PR Zamknięty bez merga (Odrzucony)
        else:
            rejected_count += 1

    avg_merge_seconds = sum(merge_times) / len(merge_times) if merge_times else 0
    avg_merge_days = round(avg_merge_seconds / 86400, 1)

    return {
        "merged": merged_count,
        "rejected": rejected_count,
        "open": open_count,
        "total": total_prs,
        "average_time_to_merge": avg_merge_days
    }


def analyze_activity(owner_repo: str, headers: dict) -> dict:
    """Compare recent activity with a year ago."""
    # TODO: Twój kod tutaj
    # Endpoint: GET /repos/{owner}/{repo}/commits
    # Użyj parametrów since= i until= z datami ISO 8601
    url = f"{GITHUB_API}/repos/{owner_repo}/commits"

    # Dzisiaj
    now = datetime.now()

    # Daty dla ostatniego miesiąca
    month_ago = now - timedelta(days=30)
    month_ago_iso = month_ago.isoformat() + "Z"

    # Daty "rok temu" 
    year_ago_start = now - timedelta(days=365+30)
    year_ago_end = now - timedelta(days=365)
    year_ago_start_iso = year_ago_start.isoformat() + "Z"
    year_ago_end_iso = year_ago_end.isoformat() + "Z"

    params1 = {
        'since': month_ago_iso,
        'per_page': 1
    } 

    params2 = {
        'since': year_ago_start_iso,
        'until': year_ago_end_iso,
        'per_page': 1
    } 

    r1 = requests.get(url, params=params1, headers=headers)
    r1.raise_for_status()
    r2 = requests.get(url, params=params2, headers=headers)
    r2.raise_for_status()
    
    if 'Link' in r1.headers:
        links = r1.headers['Link']
        match1 = re.search(r'page=(\d+)>; rel="last"', links)
        commits_last_month = int(match1.group(1)) if match1 else len(r1.json())
    else:
        commits_last_month = len(r1.json())

    if 'Link' in r2.headers:
        links = r2.headers['Link']
        match2 = re.search(r'page=(\d+)>; rel="last"', links)
        commits_last_year = int(match2.group(1)) if match2 else len(r2.json())
    else:
        commits_last_year = len(r2.json())

    cont_url = f"{GITHUB_API}/repos/{owner_repo}/contributors"

    all_contributors = fetch_paginated(
        url=cont_url, 
        headers=headers, 
        params={"per_page": 100}, 
        max_items=5000
    )
    
    unique_contributors = len(all_contributors)

    return {
        'commits_last_month': commits_last_month,
        'commits_last_year': commits_last_year,
        'unique_contributors': unique_contributors
    }


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

    ### printing issues stats ###
    print()
    print(f"--- ISSUES ---")  
    print(f" Zamkniete:  {issues['percent_closed']}%")
    print(f" Sredni czas do odpowiedzi:  {issues['time_to_comment']} days")
    print("  Top etykiety:")
    for label, count in issues['common_labels']:
        print(f" - {label} ({count} razy)")
    
    ### printing request stats ###
    total = prs['total'] 
    print()
    print("--- PULL REQUESTS ---")
    if total > 0:
        print(f" Zmergowane: {prs['merged']} ({round(prs['merged']/total*100, 1)}%)")
        print(f" Odrzucone:  {prs['rejected']} ({round(prs['rejected']/total*100, 1)}%)")
        print(f" Otwarte:    {prs['open']} ({round(prs['open']/total*100, 1)}%)")
        print(f" Średni czas do merga: {prs['average_time_to_merge']} dni")
    else:
        print("Nie znalezionio zadnych Pull Requestow...")

    ### printing activity stats ###
    print()
    print("--- AKTYWNOSC ---")
    print(f"  Commitow ostatni miesiac:  {activity['commits_last_month']}")
    print(f"  Commitow rok temu:  {activity['commits_last_year']}")
    print(f"  Unikatowi kontrybutorzy:  {activity['unique_contributors']}")


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
