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


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def analyze_issues(owner_repo: str, headers: dict, count: int = 100) -> dict:
    """Analyze recent issues: response time, close rate, top labels."""
    raw = fetch_paginated(
        f"{GITHUB_API}/repos/{owner_repo}/issues",
        headers,
        params={"state": "all", "sort": "created", "direction": "desc"},
        max_items=count,
    )

    issues = [i for i in raw if "pull_request" not in i]

    if not issues:
        return {"total": 0, "closed_pct": 0, "avg_response_days": None, "top_labels": []}

    closed = sum(1 for i in issues if i["state"] == "closed")
    closed_pct = round(closed / len(issues) * 100)

    label_counts: Counter = Counter()
    for issue in issues:
        for label in issue.get("labels", []):
            label_counts[label["name"]] += 1
    top_labels = label_counts.most_common(5)

    response_times: list[float] = []
    sample = issues[:20]
    for issue in sample:
        comments_url = issue.get("comments_url")
        if issue.get("comments", 0) == 0 or not comments_url:
            continue
        r = requests.get(comments_url, headers=headers, params={"per_page": 1})
        if r.status_code != 200:
            continue
        comments = r.json()
        if comments:
            created = parse_dt(issue["created_at"])
            first_comment = parse_dt(comments[0]["created_at"])
            if created and first_comment:
                delta = (first_comment - created).total_seconds() / 86400
                response_times.append(delta)

    avg_response = round(sum(response_times) / len(response_times), 1) if response_times else None

    return {
        "total": len(issues),
        "closed_pct": closed_pct,
        "avg_response_days": avg_response,
        "top_labels": top_labels,
    }


def analyze_pull_requests(owner_repo: str, headers: dict, count: int = 50) -> dict:
    """Analyze recent pull requests: merge time, merge rate."""
    raw = fetch_paginated(
        f"{GITHUB_API}/repos/{owner_repo}/pulls",
        headers,
        params={"state": "all", "sort": "created", "direction": "desc"},
        max_items=count,
    )

    if not raw:
        return {"total": 0, "merged_pct": 0, "closed_pct": 0, "open_pct": 0,
                "avg_merge_days": None}

    merged = [pr for pr in raw if pr.get("merged_at")]
    closed_not_merged = [pr for pr in raw if pr["state"] == "closed" and not pr.get("merged_at")]
    open_prs = [pr for pr in raw if pr["state"] == "open"]

    total = len(raw)
    merged_pct = round(len(merged) / total * 100)
    closed_pct = round(len(closed_not_merged) / total * 100)
    open_pct = round(len(open_prs) / total * 100)

    merge_times: list[float] = []
    for pr in merged:
        created = parse_dt(pr["created_at"])
        merged_at = parse_dt(pr["merged_at"])
        if created and merged_at:
            delta = (merged_at - created).total_seconds() / 86400
            merge_times.append(delta)

    avg_merge = round(sum(merge_times) / len(merge_times), 1) if merge_times else None

    return {
        "total": total,
        "merged_pct": merged_pct,
        "closed_pct": closed_pct,
        "open_pct": open_pct,
        "avg_merge_days": avg_merge,
    }


def analyze_activity(owner_repo: str, headers: dict) -> dict:
    """Compare recent commit activity with the same period a year ago."""
    now = datetime.now(timezone.utc)

    def count_commits(since: datetime, until: datetime) -> int:
        items = fetch_paginated(
            f"{GITHUB_API}/repos/{owner_repo}/commits",
            headers,
            params={
                "since": since.isoformat(),
                "until": until.isoformat(),
            },
            max_items=500,
        )
        return len(items)

    recent_until = now
    recent_since = now - timedelta(days=30)
    recent_count = count_commits(recent_since, recent_until)

    year_ago_until = now - timedelta(days=365)
    year_ago_since = year_ago_until - timedelta(days=30)
    year_ago_count = count_commits(year_ago_since, year_ago_until)

    if year_ago_count == 0:
        trend = "brak danych rok temu"
    else:
        diff_pct = round((recent_count - year_ago_count) / year_ago_count * 100)
        if diff_pct > 0:
            trend = f"wzrost o {diff_pct}%"
        elif diff_pct < 0:
            trend = f"spadek o {abs(diff_pct)}%"
        else:
            trend = "bez zmian"

    contributors_url = f"{GITHUB_API}/repos/{owner_repo}/contributors"
    try:
        contrib_resp = requests.get(contributors_url, headers=headers,
                                    params={"per_page": 1, "anon": "false"})
        link = contrib_resp.headers.get("Link", "")
        total_contributors = None
        for part in link.split(","):
            if 'rel="last"' in part:
                import re
                m = re.search(r"[?&]page=(\d+)", part)
                if m:
                    total_contributors = int(m.group(1))
        if total_contributors is None:
            all_contribs = requests.get(contributors_url, headers=headers,
                                        params={"per_page": 100}).json()
            total_contributors = len(all_contribs) if isinstance(all_contribs, list) else "N/A"
    except Exception:
        total_contributors = "N/A"

    return {
        "recent_commits": recent_count,
        "year_ago_commits": year_ago_count,
        "trend": trend,
        "total_contributors": total_contributors,
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
    print(f"  Licencja:       {license_name.get('spdx_id', 'N/A') if license_name else 'N/A'}")

    print(f"\n--- Issues (ostatnie {issues['total']}) ---")
    if issues["total"] > 0:
        print(f"  Zamknięte:                   {issues['closed_pct']}%")
        if issues["avg_response_days"] is not None:
            print(f"  Średni czas do odpowiedzi:   {issues['avg_response_days']} dni")
        else:
            print(f"  Średni czas do odpowiedzi:   brak danych")
        if issues["top_labels"]:
            labels_str = ", ".join(f"{name} ({cnt})" for name, cnt in issues["top_labels"])
            print(f"  Top etykiety:                {labels_str}")
        else:
            print(f"  Top etykiety:                brak")
    else:
        print("  Brak issues do analizy.")

    print(f"\n--- Pull Requests (ostatnie {prs['total']}) ---")
    if prs["total"] > 0:
        print(f"  Zmergowane:                  {prs['merged_pct']}%")
        print(f"  Odrzucone:                   {prs['closed_pct']}%")
        print(f"  Otwarte:                     {prs['open_pct']}%")
        if prs["avg_merge_days"] is not None:
            print(f"  Średni czas do merge:        {prs['avg_merge_days']} dni")
        else:
            print(f"  Średni czas do merge:        brak danych")
    else:
        print("  Brak PR-ów do analizy.")

    print(f"\n--- Aktywność ---")
    print(f"  Commitów (ostatni miesiąc):  {activity['recent_commits']}")
    print(f"  Commitów (rok temu):         {activity['year_ago_commits']}")
    print(f"  Trend:                       {activity['trend']}")
    print(f"  Unikalni kontrybutorzy:      {activity['total_contributors']}")
    print()


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