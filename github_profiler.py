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


def _parse_iso_date(date_str: str | None) -> datetime | None:
    """Parse ISO 8601 date string to datetime."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _days_between(start: datetime | None, end: datetime | None) -> float | None:
    """Return days between two datetimes."""
    if not start or not end:
        return None
    delta = end - start
    return delta.total_seconds() / 86400


def analyze_issues(owner_repo: str, headers: dict,
                   count: int = 100) -> dict:
    """Analyze recent issues: response time, close rate, top labels."""
    url = f"{GITHUB_API}/repos/{owner_repo}/issues"
    params = {"state": "all", "sort": "created", "direction": "desc", "per_page": 100}

    # Fetch until we have enough issues (filter out PRs)
    all_items = []
    current_url = url
    while len(all_items) < count:
        response = requests.get(current_url, headers=headers, params=params)
        response.raise_for_status()
        page = response.json()
        params = {}

        for item in page:
            if "pull_request" not in item:
                all_items.append(item)
                if len(all_items) >= count:
                    break

        if len(page) < 100:
            break

        link_header = response.headers.get("Link", "")
        current_url = None
        for part in link_header.split(","):
            if 'rel="next"' in part:
                current_url = part.split(";")[0].strip(" <>")
        if not current_url:
            break

    issues = all_items[:count]

    # Close rate
    closed = sum(1 for i in issues if i.get("state") == "closed")
    closed_pct = round(100 * closed / len(issues)) if issues else 0

    # Top 5 labels
    label_counts = Counter()
    for issue in issues:
        for label in issue.get("labels", []):
            name = label.get("name", "")
            if name:
                label_counts[name] += 1
    top_labels = [(name, cnt) for name, cnt in label_counts.most_common(5)]

    # Avg time to first response (limit to 20 issues to avoid too many API calls - per FAQ)
    response_times = []
    max_issues_for_response = 20
    for issue in issues:
        if len(response_times) >= max_issues_for_response:
            break
        created = _parse_iso_date(issue.get("created_at"))
        if not created:
            continue
        comments_url = issue.get("comments_url")
        if not comments_url or issue.get("comments", 0) == 0:
            continue
        r = requests.get(
            comments_url,
            headers=headers,
            params={"per_page": 1, "sort": "created", "direction": "asc"},
        )
        r.raise_for_status()
        comments = r.json()
        if not comments:
            continue
        first_comment = _parse_iso_date(comments[0].get("created_at"))
        days = _days_between(created, first_comment)
        if days is not None and days >= 0:
            response_times.append(days)

    avg_response_days = round(sum(response_times) / len(response_times), 1) if response_times else None

    return {
        "closed_pct": closed_pct,
        "avg_response_days": avg_response_days,
        "top_labels": top_labels,
    }


def analyze_pull_requests(owner_repo: str, headers: dict,
                          count: int = 50) -> dict:
    """Analyze recent pull requests: merge time, merge rate."""
    url = f"{GITHUB_API}/repos/{owner_repo}/pulls"
    params = {"state": "all", "sort": "created", "direction": "desc", "per_page": 50}
    prs = fetch_paginated(url, headers, params, max_items=count)

    merged = 0
    rejected = 0
    open_count = 0
    merge_times = []

    for pr in prs:
        state = pr.get("state", "")
        merged_at = pr.get("merged_at")
        closed_at = pr.get("closed_at")
        created_at = _parse_iso_date(pr.get("created_at"))

        if state == "open":
            open_count += 1
        elif merged_at:
            merged += 1
            end = _parse_iso_date(merged_at)
            days = _days_between(created_at, end)
            if days is not None and days >= 0:
                merge_times.append(days)
        else:
            rejected += 1

    total = len(prs)
    merged_pct = round(100 * merged / total) if total else 0
    rejected_pct = round(100 * rejected / total) if total else 0
    open_pct = round(100 * open_count / total) if total else 0
    avg_merge_days = round(sum(merge_times) / len(merge_times), 1) if merge_times else None

    return {
        "merged_pct": merged_pct,
        "rejected_pct": rejected_pct,
        "open_pct": open_pct,
        "avg_merge_days": avg_merge_days,
    }


def analyze_activity(owner_repo: str, headers: dict) -> dict:
    """Compare recent activity with a year ago."""
    now = datetime.now(timezone.utc)
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month_end = this_month_start - timedelta(seconds=1)
    last_month_start = (last_month_end.replace(day=1)
                       if last_month_end.month > 1
                       else last_month_end.replace(year=last_month_end.year - 1, month=12, day=1))

    year_ago_end = last_month_end - timedelta(days=365)
    year_ago_start = last_month_start - timedelta(days=365)

    def count_commits(since: datetime, until: datetime) -> int:
        url = f"{GITHUB_API}/repos/{owner_repo}/commits"
        params = {
            "since": since.isoformat(),
            "until": until.isoformat(),
            "per_page": 100,
        }
        total = 0
        current_url = url
        while True:
            r = requests.get(current_url, headers=headers, params=params)
            r.raise_for_status()
            data = r.json()
            total += len(data)
            params = {}
            if len(data) < 100:
                break
            link_header = r.headers.get("Link", "")
            current_url = None
            for part in link_header.split(","):
                if 'rel="next"' in part:
                    current_url = part.split(";")[0].strip(" <>")
            if not current_url:
                break
        return total

    commits_this_month = count_commits(last_month_start, last_month_end)
    commits_year_ago = count_commits(year_ago_start, year_ago_end)

    # Unique contributors - fetch all pages
    url = f"{GITHUB_API}/repos/{owner_repo}/contributors"
    contributors = []
    current_url = url
    params = {"per_page": 100}
    while current_url:
        r = requests.get(current_url, headers=headers, params=params)
        r.raise_for_status()
        contributors.extend(r.json())
        params = {}
        link_header = r.headers.get("Link", "")
        current_url = None
        for part in link_header.split(","):
            if 'rel="next"' in part:
                current_url = part.split(";")[0].strip(" <>")

    unique_contributors = len(contributors)

    # Trend
    if commits_year_ago > 0:
        change_pct = round(100 * (commits_this_month - commits_year_ago) / commits_year_ago)
        if change_pct > 0:
            trend = f"wzrost o {change_pct}%"
        elif change_pct < 0:
            trend = f"spadek o {abs(change_pct)}%"
        else:
            trend = "bez zmian"
    else:
        trend = "brak danych rok temu"

    return {
        "commits_this_month": commits_this_month,
        "commits_year_ago": commits_year_ago,
        "unique_contributors": unique_contributors,
        "trend": trend,
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

    print(f"\n--- Issues (ostatnie 100) ---")
    print(f"  Zamknięte:                   {issues['closed_pct']}%")
    avg_resp = issues.get('avg_response_days')
    resp_str = f"{avg_resp} dni" if avg_resp is not None else "N/A"
    print(f"  Średni czas do odpowiedzi:   {resp_str}")
    labels_str = ", ".join(f"{n} ({c})" for n, c in issues['top_labels']) or "brak"
    print(f"  Top etykiety:                {labels_str}")

    print(f"\n--- Pull Requests (ostatnie 50) ---")
    print(f"  Zmergowane:                  {prs['merged_pct']}%")
    print(f"  Odrzucone:                   {prs['rejected_pct']}%")
    print(f"  Otwarte:                     {prs['open_pct']}%")
    avg_merge = prs.get('avg_merge_days')
    merge_str = f"{avg_merge} dni" if avg_merge is not None else "N/A"
    print(f"  Średni czas do merge:        {merge_str}")

    print(f"\n--- Aktywność ---")
    print(f"  Commitów (ostatni miesiąc):  {activity['commits_this_month']}")
    print(f"  Commitów (rok temu):         {activity['commits_year_ago']}")
    print(f"  Unikatowi kontrybutorzy:    {activity['unique_contributors']}")
    print(f"  Trend:                       {activity['trend']}")


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
