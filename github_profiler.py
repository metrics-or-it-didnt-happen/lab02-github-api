#!/usr/bin/env python3
"""GitHub Profiler - repository health analysis via GitHub API."""

import os
import sys
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


def fetch_paginated(
    url: str, headers: dict, params: dict | None = None, max_items: int = 100
) -> list:
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


def parse_github_date(date_str: str) -> datetime:
    if not date_str:
        return None
    return datetime.fromisoformat(date_str.replace("Z", "+00:00"))


def analyze_issues(owner_repo: str, headers: dict, count: int = 100) -> dict:
    """Analyze recent issues: response time, close rate, top labels."""

    url = f"{GITHUB_API}/repos/{owner_repo}/issues"
    params = {"state": "all", "sort": "created", "direction": "desc", "per_page": 100}
    raw_items = fetch_paginated(url, headers, params, max_items=4 * count)
    issues = [i for i in raw_items if "pull_request" not in i][:count]

    response_times = []
    for i in issues:
        if i["comments"] > 0:
            resp = requests.get(
                i["comments_url"], headers=headers, params={"per_page": 1}
            )
            if resp.status_code == 200 and resp.json():
                first_comment_date = parse_github_date(resp.json()[0]["created_at"])
                created_date = parse_github_date(i["created_at"])
                diff = (first_comment_date - created_date).total_seconds() / 86400
                response_times.append(diff)

    if len(issues) == 0:
        return {
            "ave_response_time": 0,
            "percent_closed": 0,
            "percent_open": 0,
            "top_5_labels": [],
            "total": 0,
        }

    sum_closed = len([i for i in issues if i["state"] == "closed"])
    percent_closed = (sum_closed / len(issues)) * 100.0
    percent_open = 100.0 - percent_closed

    labels = []
    for i in issues:
        labels.extend([label["name"] for label in i.get("labels", [])])

    return {
        "ave_response_time": sum(response_times) / len(response_times),
        "percent_closed": percent_closed,
        "percent_open": percent_open,
        "top_5_labels": Counter(labels).most_common(5),
        "total": len(issues),
    }


def analyze_pull_requests(owner_repo: str, headers: dict, count: int = 50) -> dict:
    """Analyze recent pull requests: merge time, merge rate."""

    url = f"{GITHUB_API}/repos/{owner_repo}/pulls"
    params = {"state": "all", "sort": "created", "direction": "desc", "per_page": 50}
    raw_items = fetch_paginated(url, headers, params, max_items=count)

    merged = [p for p in raw_items if p.get("merged_at") is not None]
    rejected = [
        p for p in raw_items if p["state"] == "closed" and p.get("merged_at") is None
    ]
    accepted = [p for p in raw_items if p["state"] == "open"]
    merged_duration = []
    for p in merged:
        created = parse_github_date(p["created_at"])
        merged_at = parse_github_date(p["merged_at"])
        merged_duration.append((merged_at - created).total_seconds() / 86400)
        # 86400s = 24h = dzien

    total = len(raw_items)

    return {
        "merged_pct": (len(merged) / total) * 100,
        "rejected_pct": (len(rejected) / total) * 100,
        "open_pct": (len(accepted) / total) * 100,
        "avg_merge_days": (
            sum(merged_duration) / len(merged_duration) if merged_duration else 0
        ),
    }


def analyze_activity(owner_repo: str, headers: dict, count: int = 100) -> dict:
    """Compare recent activity with a year ago."""

    today = datetime.now()
    month_ago = (today - timedelta(days=30)).isoformat()
    year_ago = (today - timedelta(days=365)).isoformat()
    until = (today - timedelta(days=335)).isoformat()

    url = f"{GITHUB_API}/repos/{owner_repo}/commits"
    params = {"since": month_ago, "per_page": 100}
    params2 = {"since": year_ago, "until": until, "per_page": 100}

    raw_items_last_month = fetch_paginated(url, headers, params, max_items=count)
    raw_items_prev_month = fetch_paginated(url, headers, params2, max_items=count)

    sum_last_month = len(raw_items_last_month)
    sum_prev_month = len(raw_items_prev_month)

    unique_cunt = set()

    for item in raw_items_last_month:
        author_info = item.get("commit", {}).get("author", {})
        author_email = author_info.get("email")

        if author_email:
            unique_cunt.add(author_email)

    return {
        "sum_last_month": sum_last_month,
        "sum_prev_month": sum_prev_month,
        "unique_cont": len(unique_cunt),
    }


def print_report(repo_info: dict, issues: dict, prs: dict, activity: dict) -> None:
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
    print(
        f"  Licencja:       {license_name.get('spdx_id', 'N/A') if license_name else 'N/A'}"
    )

    print(f"\n--- Issues (ostatnie {issues['total']}) --")
    print(
        f"  Średni czas do pierwszej odpowiedzi:       {issues['ave_response_time']:.2f} dni"
    )
    print(
        f"  Procent zamkniętych vs otwartych:          {issues['percent_closed']:.1f}% vs {issues['percent_open']:.1f}%"
    )

    labels_formatted = ", ".join(
        [f"{name} ({count})" for name, count in issues["top_5_labels"]]
    )
    print(
        f"  Top 5 najczęstszych etykiet (labels):      {labels_formatted if labels_formatted else 'Brak'}"
    )

    print(f"\n--- Pull Requests (ostatnie 50) ---")
    print(f"  Średni czas do merge:        {prs['avg_merge_days']:.1f} dni")
    print(f"  Zmergowane:                  {prs['merged_pct']:.0f}%")
    print(f"  Odrzucone:                   {prs['rejected_pct']:.0f}%")
    print(f"  Otwarte:                     {prs['open_pct']:.0f}%")

    print(f"\n--- Aktywność ---")
    print(f"  Commitów (ostatni miesiąc):       {activity['sum_last_month']}")
    print(f"  Commitów (rok temu):              {activity['sum_prev_month']}")
    print(f"  Liczba unikatowych kontrybutorów: {activity["unique_cont"]}")


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
