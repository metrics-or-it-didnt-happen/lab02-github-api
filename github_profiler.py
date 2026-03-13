#!/usr/bin/env python3
"""GitHub Profiler - repository health analysis via GitHub API."""

import os
import sys
from collections import Counter
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
    url = f"{GITHUB_API}/repos/{owner_repo}/issues"
    params = {"state": "all", "sort": "created", "direction": "desc"}
    
    all_items = fetch_paginated(url, headers, params, max_items=count * 5)
    issues = [i for i in all_items if "pull_request" not in i][:count]
    closed_issues = [i for i in issues if i.get("state") == "closed"]

    label_counter = Counter()
    for issue in issues:
        for label in issue.get("labels", []):
            label_counter[label["name"]] += 1

    response_times = []
    issues_with_comments = [i for i in issues if i.get("comments", 0) > 0][:20]
    
    for issue in issues_with_comments:
        comments_url = issue["comments_url"]
        try:
            comments_resp = requests.get(comments_url, headers=headers, params={"per_page": 1})
            comments_resp.raise_for_status()
            comments = comments_resp.json()
            if comments:
                created_at = datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00"))
                comment_at = datetime.fromisoformat(comments[0]["created_at"].replace("Z", "+00:00"))
                delta_days = (comment_at - created_at).total_seconds() / 86400.0
                response_times.append(delta_days)
        except Exception:
            pass # skip komentarzy

    avg_response_time = sum(response_times) / len(response_times) if response_times else 0.0

    return {
        "total": len(issues),
        "closed": len(closed_issues),
        "top_labels": label_counter.most_common(3),
        "avg_response_days": avg_response_time
    }

def analyze_pull_requests(owner_repo: str, headers: dict,
                          count: int = 50) -> dict:
    """Analyze recent pull requests: merge time, merge rate."""
    url = f"{GITHUB_API}/repos/{owner_repo}/pulls"
    params = {"state": "all", "sort": "created", "direction": "desc"}
    prs = fetch_paginated(url, headers, params, max_items=count)

    merged = [p for p in prs if p.get("merged_at")]
    rejected = [p for p in prs if p.get("state") == "closed" and not p.get("merged_at")]
    still_open = [p for p in prs if p.get("state") == "open"]

    merge_times = []
    for p in merged:
        created_at = datetime.fromisoformat(p["created_at"].replace("Z", "+00:00"))
        merged_at = datetime.fromisoformat(p["merged_at"].replace("Z", "+00:00"))
        delta_days = (merged_at - created_at).total_seconds() / 86400.0
        merge_times.append(delta_days)
        
    avg_merge_time = sum(merge_times) / len(merge_times) if merge_times else 0.0

    return {
        "total": len(prs),
        "merged": len(merged),
        "rejected": len(rejected),
        "open": len(still_open),
        "avg_merge_days": avg_merge_time
    }

def analyze_activity(owner_repo: str, headers: dict) -> dict:
    """Compare recent activity with a year ago."""
    url = f"{GITHUB_API}/repos/{owner_repo}/commits" 
    
    now = datetime.now(timezone.utc)
    month_ago = now - timedelta(days=30)
    
    year_ago_start = now - timedelta(days=365)
    year_ago_end = now - timedelta(days=335)

    recent_params = {"since": month_ago.isoformat(), "until": now.isoformat()}
    recent_commits = fetch_paginated(url, headers, recent_params, max_items=100)

    old_params = {"since": year_ago_start.isoformat(), "until": year_ago_end.isoformat()}
    old_commits = fetch_paginated(url, headers, old_params, max_items=100)

    return {
        "recent_commits": len(recent_commits),
        "old_commits": len(old_commits)
    }

def print_report(repo_info: dict, issues: dict, prs: dict,
                 activity: dict) -> None:
    """Print formatted report to console."""
    print(f"\n{'=' * 60}")
    print(f"PROFIL REPOZYTORIUM: {repo_info['full_name']}")
    print(f"{'=' * 60}")

    print("\n--- Podstawowe metryki ---")
    print(f"  Gwiazdki:       {repo_info.get('stargazers_count', 0):,}")
    print(f"  Forki:          {repo_info.get('forks_count', 0):,}")
    print(f"  Otwarte issues: {repo_info.get('open_issues_count', 0):,}")
    print(f"  Język:          {repo_info.get('language', 'N/A')}")
    license_name = repo_info.get("license") or {}
    print(f"  Licencja:       {license_name.get('spdx_id', 'N/A')}")

    issues_tot = issues['total']
    closed_pct = int((issues['closed'] / issues_tot * 100)) if issues_tot > 0 else 0
    labels_str = ", ".join([f"{name} ({count})" for name, count in issues['top_labels']])
    
    print(f"\n--- Issues (ostatnie {issues_tot}) ---")
    print(f"  Zamknięte:                   {closed_pct}%")
    print(f"  Średni czas do odpowiedzi:   {issues['avg_response_days']:.1f} dni")
    print(f"  Top etykiety:                {labels_str if labels_str else 'Brak'}")

    prs_tot = prs['total']
    merged_pct = int((prs['merged'] / prs_tot * 100)) if prs_tot > 0 else 0
    rejected_pct = int((prs['rejected'] / prs_tot * 100)) if prs_tot > 0 else 0
    open_pct = int((prs['open'] / prs_tot * 100)) if prs_tot > 0 else 0

    print(f"\n--- Pull Requests (ostatnie {prs_tot}) ---")
    print(f"  Zmergowane:                  {merged_pct}%")
    print(f"  Odrzucone:                   {rejected_pct}%")
    print(f"  Otwarte:                     {open_pct}%")
    print(f"  Średni czas do merge:        {prs['avg_merge_days']:.1f} dni")

    recent_c = activity['recent_commits']
    old_c = activity['old_commits']
    
    if old_c > 0:
        diff_pct = ((recent_c - old_c) / old_c) * 100
        if diff_pct > 0:
            trend_str = f"wzrost o {int(diff_pct)}%"
        elif diff_pct < 0:
            trend_str = f"spadek o {abs(int(diff_pct))}%"
        else:
            trend_str = "bez zmian"
    else:
        trend_str = "brak danych z zeszłego roku"

    print(f"\n--- Aktywność ---")
    print(f"  Commitów (ostatni miesiąc):  {recent_c}")
    print(f"  Commitów (rok temu):         {old_c}")
    print(f"  Trend:                       {trend_str}\n")


def print_comparison(repo1_name: str, info1: dict, iss1: dict, prs1: dict, act1: dict,
                     repo2_name: str, info2: dict, iss2: dict, prs2: dict, act2: dict) -> None:
    """Print formatted comparison table for two repositories."""
    print(f"\nPORÓWNANIE: {repo1_name} vs {repo2_name}")
    print("=" * 60)
    
    n1 = repo1_name.split('/')[-1]
    n2 = repo2_name.split('/')[-1]
    
    print(f"{'Metryka':<25}{n1:>15}{n2:>15}")
    print("-" * 60)

    def calc_iss_pct(iss):
        return int((iss['closed'] / iss['total'] * 100)) if iss['total'] > 0 else 0
    
    def calc_pr_pct(prs):
        return int((prs['merged'] / prs['total'] * 100)) if prs['total'] > 0 else 0

    def row(name, val1, val2):
        print(f"{name:<25}{str(val1):>15}{str(val2):>15}")

    row("Gwiazdki", f"{info1.get('stargazers_count', 0):,}", f"{info2.get('stargazers_count', 0):,}")
    row("Forki", f"{info1.get('forks_count', 0):,}", f"{info2.get('forks_count', 0):,}")
    row("Otwarte issues", f"{info1.get('open_issues_count', 0):,}", f"{info2.get('open_issues_count', 0):,}")
    row("% zamkniętych issues", f"{calc_iss_pct(iss1)}%", f"{calc_iss_pct(iss2)}%")
    row("Śr. czas odpowiedzi", f"{iss1['avg_response_days']:.1f} dni", f"{iss2['avg_response_days']:.1f} dni")
    row("% zmergowanych PR", f"{calc_pr_pct(prs1)}%", f"{calc_pr_pct(prs2)}%")
    row("Śr. czas merge", f"{prs1['avg_merge_days']:.1f} dni", f"{prs2['avg_merge_days']:.1f} dni")
    row("Commitów (ost. miesiąc)", act1['recent_commits'], act2['recent_commits'])
    
    print("\nVerdict: ", end="")
    
    score1 = 0
    score2 = 0
    
    if iss1['avg_response_days'] < iss2['avg_response_days']: score1 += 1
    else: score2 += 1
    
    if prs1['avg_merge_days'] < prs2['avg_merge_days']: score1 += 1
    else: score2 += 1
    
    if act1['recent_commits'] > act2['recent_commits']: score1 += 1
    else: score2 += 1
    
    if score1 > score2:
        print(f"{n1} wygląda aktywniej i szybciej reaguje na issues oraz Pull Requesty.\n")
    elif score2 > score1:
        print(f"{n2} wygląda aktywniej i szybciej reaguje na issues oraz Pull Requesty.\n")
    else:
        print("Oba repozytoria wydają się podobnie aktywne i zdrowe.\n")


def main():
    if len(sys.argv) < 2:
        print("Użycie 1 (pojedyncze repo): python github_profiler.py <owner/repo>")
        print("Użycie 2 (porównanie):      python github_profiler.py <owner/repo1> <owner/repo2>")
        print("Przykład:                   python github_profiler.py psf/requests encode/httpx")
        sys.exit(1)

    headers = get_headers()

    if len(sys.argv) == 2:
        owner_repo = sys.argv[1]
        print(f"Profiluję {owner_repo}...")
        repo_info = get_repo_info(owner_repo, headers)
        issues = analyze_issues(owner_repo, headers)
        prs = analyze_pull_requests(owner_repo, headers)
        activity = analyze_activity(owner_repo, headers)
        print_report(repo_info, issues, prs, activity)

    elif len(sys.argv) >= 3:
        repo1 = sys.argv[1]
        repo2 = sys.argv[2]
        
        print(f"Pobieram dane dla {repo1}...")
        info1 = get_repo_info(repo1, headers)
        iss1 = analyze_issues(repo1, headers)
        prs1 = analyze_pull_requests(repo1, headers)
        act1 = analyze_activity(repo1, headers)

        print(f"Pobieram dane dla {repo2}...")
        info2 = get_repo_info(repo2, headers)
        iss2 = analyze_issues(repo2, headers)
        prs2 = analyze_pull_requests(repo2, headers)
        act2 = analyze_activity(repo2, headers)

        print_comparison(repo1, info1, iss1, prs1, act1, 
                         repo2, info2, iss2, prs2, act2)


if __name__ == "__main__":
    main()