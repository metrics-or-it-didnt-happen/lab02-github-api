#!/usr/bin/env python3
"""GitHub Profiler - repository health analysis via GitHub API."""

from collections import Counter
import os
import sys
from datetime import datetime, timedelta, timezone
from statistics import mean

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

    raw_fetch = fetch_paginated(
        f"{GITHUB_API}/repos/{owner_repo}/issues",
        headers=headers,
        params={"state": "all", "sort": "created", "direction":"desc"},
        max_items=count
    )

    filtered_fetch = [issue for issue in raw_fetch if "pull_request" not in issue]

    #get closed issues
    no_closed = 0
    no_closed_percent = 0.0

    if len(filtered_fetch) != 0:
        for issue in filtered_fetch:
            if issue['state'] == 'closed':
                no_closed += 1
    
        no_closed_percent = round(no_closed / len(filtered_fetch) * 100, 0)

    # get response time
    response_times = []
    average_response_days = 0
    no_wanted_issues = 20
    head_filtered_fetch = filtered_fetch[:no_wanted_issues]

    for issue in head_filtered_fetch:
        comment_url = issue.get("comments_url")
        if issue.get('comments', 0) != 0 and comment_url:
            first_comment = requests.get(comment_url, headers=headers, params={"per_page": 1})
            if first_comment.status_code == 200:
                comment = first_comment.json()
                if comment:
                    start = datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00")) 
                    end = datetime.fromisoformat(comment[0]["created_at"].replace("Z", "+00:00")) 

                    if start and end:
                        time = (end - start).total_seconds() / 86400
                        response_times.append(time)
    if len(response_times) == 0:
        average_response_days = "brak danych do policzenia" #...dni
    else:
        average_response_days = round(sum(response_times) / len(response_times), 1)
    
    #get labels
    labels_counter = Counter()
    for issue in filtered_fetch:
        for label in issue.get("labels", []):
            labels_counter[label["name"]] += 1
    
    labels_top = labels_counter.most_common(5)

    return {
        "total_issues": len(filtered_fetch),
        "no_closed_percent": no_closed_percent,
        "average_response": average_response_days,
        "labels_top": labels_top
    }


def analyze_pull_requests(owner_repo: str, headers: dict,
                          count: int = 50) -> dict:
    """Analyze recent pull requests: merge time, merge rate."""
    raw_fetch = fetch_paginated(
        f"{GITHUB_API}/repos/{owner_repo}/pulls",
        headers=headers,
        params={"state": "all", "sort": "created", "direction":"desc"},
        max_items=count
    )

    # get totals
    total_pull_req = len(raw_fetch)
    merged = [pull_req for pull_req in raw_fetch if pull_req.get("merged_at")]
    closed_no_merge = [pull_req for pull_req in raw_fetch if pull_req["state"] == 'closed' and not pull_req.get("merged_at")]
    open = [pull_req for pull_req in raw_fetch if pull_req["state"] == "open"]
    
    # get percentages
    merged_percent = round(len(merged) / total_pull_req * 100)
    closed_no_merge_percent = round(len(closed_no_merge) / total_pull_req * 100)
    open_percent = round(len(open) / total_pull_req * 100)

    # get average time to merge
    merge_times = []
    for pull_req in merged:
        start = datetime.fromisoformat(pull_req["created_at"].replace("Z", "+00:00")) 
        end = datetime.fromisoformat(pull_req["merged_at"].replace("Z", "+00:00")) 

        if start and end:
            time = (end - start).total_seconds() / 86400
            merge_times.append(time)

    average_merge_days = round(sum(merge_times) / len(merge_times), 1)

    return {
        "total_pull_req": total_pull_req,
        "merged_percent": merged_percent,
        "closed_no_merge_percent": closed_no_merge_percent,
        "open_percent": open_percent,
        "average_merge_days": average_merge_days
    }

def analyze_activity(owner_repo: str, headers: dict) -> dict:
    """Compare recent activity with a year ago."""
    time_now = datetime.now(timezone.utc) # get once, not for each calculation!
    # get recent commits
    recent_end = time_now 
    recent_start = time_now - timedelta(days=30)
    recent_fetch = fetch_paginated(
            f"{GITHUB_API}/repos/{owner_repo}/commits",
            headers,
            params={
                "since": recent_start.isoformat(),
                "until": recent_end.isoformat(),
            },
        )
    commits_last_month = len(recent_fetch)
    # get last year recent commits
    year_ago_recent_end = time_now - timedelta(days=335)
    year_ago_recent_start = time_now - timedelta(days=365)
    recent_year_ago_fetch = fetch_paginated(
            f"{GITHUB_API}/repos/{owner_repo}/commits",
            headers,
            params={
                "since": year_ago_recent_start.isoformat(),
                "until": year_ago_recent_end.isoformat(),
            },
        )
    commits_last_year_month = len(recent_year_ago_fetch)
    # calculate change
    if commits_last_year_month == 0:
        trend = "brak danych z zeszłego roku"
    else:
        change_percent = round((commits_last_month - commits_last_year_month) / commits_last_year_month * 100)
        if change_percent < 0:
            trend = f"spadek o {-change_percent}%"
        elif change_percent == 0:
            trend = f"bez zauważalnych zmian"
        else:
            trend = f"wzrost o {change_percent}%"

    # get contributors
    unique_contributors = ""
    # no anonymous contributors? how would we evenn count them?
    response = requests.get(f"{GITHUB_API}/repos/{owner_repo}/contributors", headers=headers, params={"per_page": 1, "anon": "false"})
    # Parse 'last' link from Link header
    link_header = response.headers.get("Link", "")
    for part in link_header.split(","):
        if 'rel="last"' in part:
            unique_contributors = (part.partition("&page=")[2].partition(">")[0])
    
    return {
        "commits_last_month": commits_last_month,
        "commits_last_year_month": commits_last_year_month,
        "trend": trend,
        "unique_contributors": unique_contributors,
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

    #issues
    print(f"\n--- Issues (ostatnie {issues['total_issues']}) ---")
    if issues["total_issues"] > 0:
        print(f"  Zamknięte:                   {issues['no_closed_percent']}%")
        print(f"  Średni czas do odpowiedzi:   {issues['average_response']} dni")
        if issues["labels_top"]:
            labels_str = ", ".join(f"{name} ({cnt})" for name, cnt in issues["labels_top"])
            print(f"  Top etykiety:                {labels_str}")
        else:
            print(f"  Top etykiety:                brak etykiet")
    else:
        print("  Nie ma issues do raportu.")

    # pull req
    print(f"\n--- Pull Requests (ostatnie {prs['total_pull_req']}) ---")
    if prs["total_pull_req"] > 0:
        print(f"  Zmergowane:                  {prs['merged_percent']}%")
        print(f"  Odrzucone:                   {prs['closed_no_merge_percent']}%")
        print(f"  Otwarte:                     {prs['open_percent']}%")
        print(f"  Średni czas do merge:        {prs['average_merge_days']} dni")
    else:
        print("  Brak PR-ów do analizy.")

    # activity
    print(f"\n--- Aktywność ---")
    print(f"  Commitów (ostatni miesiąc):  {activity['commits_last_month']}")
    print(f"  Commitów (rok temu):         {activity['commits_last_year_month']}")
    print(f"  Trend:                       {activity['trend']}")
    print(f"  Unikalni kontrybutorzy:      {activity['unique_contributors']}")
    


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