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


def parse_date(date_str: str) -> datetime:
    """Parse daty ISO 8601 z GitHub API."""
    # w 3.9/3.10 fromisoformat nie lubi 'Z'
    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def analyze_issues(owner_repo: str, headers: dict,
                   count: int = 100) -> dict:
    """Analyze recent issues: response time, close rate, top labels."""
    url = f"{GITHUB_API}/repos/{owner_repo}/issues"
    params = {
        "state": "all",
        "sort": "created",
        "direction": "desc",
        "per_page": 100,
    }

    all_items = fetch_paginated(url, headers, params, max_items=count)

    # endpoint /issues zwraca tez PRy - trzeba odfiltrowac
    issues = [i for i in all_items if "pull_request" not in i]

    if not issues:
        return {
            "total": 0,
            "closed_pct": 0,
            "avg_response_days": 0,
            "top_labels": [],
        }

    closed = sum(1 for i in issues if i["state"] == "closed")
    closed_pct = round(closed / len(issues) * 100)

    # zliczanie etykiet
    label_counter = Counter()
    for issue in issues:
        for label in issue.get("labels", []):
            label_counter[label["name"]] += 1
    top_labels = label_counter.most_common(5)

    # sredni czas do pierwszej odpowiedzi (max 20 zeby nie zjesc limitu)
    response_times = []
    for issue in issues[:20]:
        if issue["comments"] > 0:
            r = requests.get(
                issue["comments_url"],
                headers=headers,
                params={"per_page": 1},
            )
            if r.status_code == 200:
                comments = r.json()
                if comments:
                    created = parse_date(issue["created_at"])
                    first_reply = parse_date(comments[0]["created_at"])
                    diff_days = (first_reply - created).total_seconds() / 86400
                    response_times.append(diff_days)

    avg_response = 0
    if response_times:
        avg_response = round(sum(response_times) / len(response_times), 1)

    return {
        "total": len(issues),
        "closed_pct": closed_pct,
        "avg_response_days": avg_response,
        "top_labels": top_labels,
    }


def analyze_pull_requests(owner_repo: str, headers: dict,
                          count: int = 50) -> dict:
    """Analyze recent pull requests: merge time, merge rate."""
    url = f"{GITHUB_API}/repos/{owner_repo}/pulls"
    params = {
        "state": "all",
        "sort": "created",
        "direction": "desc",
        "per_page": 50,
    }

    prs = fetch_paginated(url, headers, params, max_items=count)

    if not prs:
        return {
            "total": 0,
            "merged_pct": 0,
            "rejected_pct": 0,
            "open_pct": 0,
            "avg_merge_days": 0,
        }

    merged = 0
    rejected = 0
    opened = 0
    merge_times = []

    for pr in prs:
        if pr["state"] == "open":
            opened += 1
        elif pr.get("merged_at") is not None:
            merged += 1
            created = parse_date(pr["created_at"])
            merged_at = parse_date(pr["merged_at"])
            diff = (merged_at - created).total_seconds() / 86400
            merge_times.append(diff)
        else:
            # closed + brak merged_at = odrzucony
            rejected += 1

    total = len(prs)
    avg_merge = round(sum(merge_times) / len(merge_times), 1) if merge_times else 0

    return {
        "total": total,
        "merged_pct": round(merged / total * 100),
        "rejected_pct": round(rejected / total * 100),
        "open_pct": round(opened / total * 100),
        "avg_merge_days": avg_merge,
    }


def analyze_activity(owner_repo: str, headers: dict) -> dict:
    """Compare recent activity with a year ago."""
    now = datetime.now(timezone.utc)

    # ostatni miesiac
    since_recent = (now - timedelta(days=30)).isoformat()
    until_recent = now.isoformat()

    url = f"{GITHUB_API}/repos/{owner_repo}/commits"
    recent = fetch_paginated(
        url, headers,
        params={"since": since_recent, "until": until_recent},
        max_items=300,
    )

    # rok temu, analogiczny okres 30 dni
    since_old = (now - timedelta(days=365)).isoformat()
    until_old = (now - timedelta(days=335)).isoformat()

    old = fetch_paginated(
        url, headers,
        params={"since": since_old, "until": until_old},
        max_items=300,
    )

    # unikalni kontrybutorzy z ostatniego miesiaca
    contributors = set()
    for c in recent:
        if c.get("author") and c["author"].get("login"):
            contributors.add(c["author"]["login"])
        elif c.get("commit", {}).get("author", {}).get("name"):
            contributors.add(c["commit"]["author"]["name"])

    return {
        "recent_commits": len(recent),
        "old_commits": len(old),
        "unique_contributors": len(contributors),
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
    license_info = repo_info.get("license", {})
    if license_info:
        lic = license_info.get("spdx_id", "N/A")
    else:
        lic = "N/A"
    print(f"  Licencja:       {lic}")

    # issues
    print(f"\n--- Issues (ostatnie {issues['total']}) ---")
    print(f"  Zamknięte:                   {issues['closed_pct']}%")
    print(f"  Średni czas do odpowiedzi:   {issues['avg_response_days']} dni")
    if issues["top_labels"]:
        labels_str = ", ".join(
            f"{name} ({cnt})" for name, cnt in issues["top_labels"]
        )
        print(f"  Top etykiety:                {labels_str}")

    # PRy
    print(f"\n--- Pull Requests (ostatnie {prs['total']}) ---")
    print(f"  Zmergowane:                  {prs['merged_pct']}%")
    print(f"  Odrzucone:                   {prs['rejected_pct']}%")
    print(f"  Otwarte:                     {prs['open_pct']}%")
    print(f"  Średni czas do merge:        {prs['avg_merge_days']} dni")

    # aktywnosc
    print(f"\n--- Aktywność ---")
    print(f"  Commitów (ostatni miesiąc):  {activity['recent_commits']}")
    print(f"  Commitów (rok temu):         {activity['old_commits']}")
    if activity["old_commits"] > 0:
        change = (
            (activity["recent_commits"] - activity["old_commits"])
            / activity["old_commits"]
            * 100
        )
        if change >= 0:
            print(f"  Trend:                       wzrost o {abs(round(change))}%")
        else:
            print(f"  Trend:                       spadek o {abs(round(change))}%")
    else:
        print(f"  Trend:                       brak danych z roku temu")
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
