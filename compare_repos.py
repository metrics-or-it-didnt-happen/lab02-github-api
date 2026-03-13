#!/usr/bin/env python3
"""GitHub Repos Comparator - compare health of two repositories."""

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


def fetch_paginated(url: str, headers: dict, params: dict | None = None,
                    max_items: int = 100) -> list:
    """Fetch paginated results from GitHub API."""
    items = []
    params = params or {}
    params.setdefault("per_page", min(max_items, 100))

    while url and len(items) < max_items:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        items.extend(response.json())
        params = {}

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
    params = {"state": "all", "sort": "created", "direction": "desc", "per_page": 100}
    
    issues_data = fetch_paginated(url, headers, params, max_items=count)
    
    issues = [issue for issue in issues_data if "pull_request" not in issue]
    
    if not issues:
        return {
            "closed_pct": 0,
            "avg_response_time": 0,
            "top_labels": []
        }
    
    closed_count = sum(1 for issue in issues if issue["state"] == "closed")
    closed_pct = (closed_count / len(issues)) * 100 if issues else 0
    
    response_times = []
    for issue in issues:
        if issue["comments"] > 0:
            comments_url = issue["comments_url"]
            try:
                comments = fetch_paginated(comments_url, headers, max_items=1)
                if comments:
                    issue_created = datetime.fromisoformat(
                        issue["created_at"].replace("Z", "+00:00")
                    )
                    comment_created = datetime.fromisoformat(
                        comments[0]["created_at"].replace("Z", "+00:00")
                    )
                    diff_days = (comment_created - issue_created).total_seconds() / 86400
                    response_times.append(diff_days)
            except Exception:
                pass
    
    avg_response_time = sum(response_times) / len(response_times) if response_times else 0
    
    all_labels = []
    for issue in issues:
        for label in issue.get("labels", []):
            all_labels.append(label["name"])
    
    label_counter = Counter(all_labels)
    top_labels = label_counter.most_common(10)
    
    return {
        "closed_pct": closed_pct,
        "avg_response_time": avg_response_time,
        "top_labels": top_labels
    }


def analyze_pull_requests(owner_repo: str, headers: dict,
                          count: int = 50) -> dict:
    """Analyze recent pull requests: merge time, merge rate."""
    url = f"{GITHUB_API}/repos/{owner_repo}/pulls"
    params = {"state": "all", "sort": "created", "direction": "desc", "per_page": 50}
    
    prs = fetch_paginated(url, headers, params, max_items=count)
    
    if not prs:
        return {
            "merged_pct": 0,
            "rejected_pct": 0,
            "open_pct": 0,
            "avg_merge_time": 0
        }
    
    merged_count = sum(1 for pr in prs if pr.get("merged_at") is not None)
    closed_count = sum(1 for pr in prs if pr["state"] == "closed" and pr.get("merged_at") is None)
    open_count = sum(1 for pr in prs if pr["state"] == "open")
    
    merged_pct = (merged_count / len(prs)) * 100
    rejected_pct = (closed_count / len(prs)) * 100
    open_pct = (open_count / len(prs)) * 100
    
    merge_times = []
    for pr in prs:
        if pr.get("merged_at") is not None:
            created = datetime.fromisoformat(
                pr["created_at"].replace("Z", "+00:00")
            )
            merged = datetime.fromisoformat(
                pr["merged_at"].replace("Z", "+00:00")
            )
            diff_days = (merged - created).total_seconds() / 86400
            merge_times.append(diff_days)
    
    avg_merge_time = sum(merge_times) / len(merge_times) if merge_times else 0
    
    return {
        "merged_pct": merged_pct,
        "rejected_pct": rejected_pct,
        "open_pct": open_pct,
        "avg_merge_time": avg_merge_time
    }


def analyze_activity(owner_repo: str, headers: dict) -> dict:
    """Compare recent activity with a year ago."""
    now = datetime.now(timezone.utc)
    
    since_last_month = (now - timedelta(days=30)).isoformat()
    until_now = now.isoformat()
    
    since_year_ago = (now - timedelta(days=365)).isoformat()
    until_year_ago = (now - timedelta(days=335)).isoformat()
    
    url = f"{GITHUB_API}/repos/{owner_repo}/commits"
    params_recent = {
        "since": since_last_month,
        "until": until_now,
        "per_page": 100
    }
    recent_commits = fetch_paginated(url, headers, params_recent, max_items=100)
    
    params_old = {
        "since": since_year_ago,
        "until": until_year_ago,
        "per_page": 100
    }
    old_commits = fetch_paginated(url, headers, params_old, max_items=100)
    
    recent_count = len(recent_commits)
    old_count = len(old_commits)
    
    trend_pct = ((recent_count - old_count) / old_count * 100) if old_count > 0 else 0
    
    return {
        "recent_commits": recent_count,
        "old_commits": old_count,
        "trend_pct": trend_pct
    }


def print_comparison(repo1: str, repo2: str, info1: dict, info2: dict,
                     issues1: dict, issues2: dict, prs1: dict, prs2: dict,
                     activity1: dict, activity2: dict) -> None:
    """Print formatted comparison table."""
    print(f"\nPORÓWNANIE: {info1['full_name']} vs {info2['full_name']}")
    print(f"{'=' * 70}")
    
    # Header
    print(f"{'Metryka':<30} {info1['name']:>18} {info2['name']:>18}")
    print(f"{'-' * 70}")
    
    # Basic metrics
    print(f"{'Gwiazdki':<30} {info1['stargazers_count']:>18,} {info2['stargazers_count']:>18,}")
    print(f"{'Forki':<30} {info1['forks_count']:>18,} {info2['forks_count']:>18,}")
    print(f"{'Otwarte issues':<30} {info1['open_issues_count']:>18,} {info2['open_issues_count']:>18,}")
    
    # Issues metrics
    print(f"{'% zamkniętych issues':<30} {issues1['closed_pct']:>17.0f}% {issues2['closed_pct']:>17.0f}%")
    print(f"{'Śr. czas odpowiedzi (dni)':<30} {issues1['avg_response_time']:>18.1f} {issues2['avg_response_time']:>18.1f}")
    
    # PR metrics
    print(f"{'% zmergowanych PR':<30} {prs1['merged_pct']:>17.0f}% {prs2['merged_pct']:>17.0f}%")
    print(f"{'Śr. czas merge (dni)':<30} {prs1['avg_merge_time']:>18.1f} {prs2['avg_merge_time']:>18.1f}")
    
    # Activity metrics
    print(f"{'Commitów (ost. miesiąc)':<30} {activity1['recent_commits']:>18} {activity2['recent_commits']:>18}")
    print(f"{'Commitów (rok temu)':<30} {activity1['old_commits']:>18} {activity2['old_commits']:>18}")
    
    # Calculate verdict
    print(f"\n{'=' * 70}")
    verdict = generate_verdict(info1['name'], info2['name'], issues1, issues2,
                              prs1, prs2, activity1, activity2)
    print(f"Verdict: {verdict}")


def generate_verdict(name1: str, name2: str, issues1: dict, issues2: dict,
                     prs1: dict, prs2: dict, activity1: dict, activity2: dict) -> str:
    """Generate detailed verdict based on metrics."""
    score1 = 0
    score2 = 0
    reasons1 = []
    reasons2 = []
    
    # Issues: higher closed % is better
    if issues1['closed_pct'] > issues2['closed_pct']:
        score1 += 1
        reasons1.append(f"wyższy % zamkniętych issues ({issues1['closed_pct']:.0f}%)")
    else:
        score2 += 1
        reasons2.append(f"wyższy % zamkniętych issues ({issues2['closed_pct']:.0f}%)")
    
    # Response time: lower is better
    if issues1['avg_response_time'] < issues2['avg_response_time']:
        score1 += 1
        reasons1.append(f"szybsza odpowiedź na issues ({issues1['avg_response_time']:.1f} dni)")
    else:
        score2 += 1
        reasons2.append(f"szybsza odpowiedź na issues ({issues2['avg_response_time']:.1f} dni)")
    
    # PR merge rate: higher is better
    if prs1['merged_pct'] > prs2['merged_pct']:
        score1 += 1
        reasons1.append(f"wyższy % zmergowanych PR ({prs1['merged_pct']:.0f}%)")
    else:
        score2 += 1
        reasons2.append(f"wyższy % zmergowanych PR ({prs2['merged_pct']:.0f}%)")
    
    # PR merge time: lower is better
    if prs1['avg_merge_time'] < prs2['avg_merge_time']:
        score1 += 1
        reasons1.append(f"szybszy merge PR ({prs1['avg_merge_time']:.1f} dni)")
    else:
        score2 += 1
        reasons2.append(f"szybszy merge PR ({prs2['avg_merge_time']:.1f} dni)")
    
    # Activity trend: positive is better
    if activity1['trend_pct'] > activity2['trend_pct']:
        score1 += 1
        if activity1['trend_pct'] > 0:
            reasons1.append(f"wzrost aktywności ({activity1['trend_pct']:.0f}%)")
        else:
            reasons1.append(f"stabilna aktywność")
    else:
        score2 += 1
        if activity2['trend_pct'] > 0:
            reasons2.append(f"wzrost aktywności ({activity2['trend_pct']:.0f}%)")
        else:
            reasons2.append(f"stabilna aktywność")
    
    if score1 > score2:
        reason_str = ", ".join(reasons1)
        return f"{name1} wygląda zdrowiej: {reason_str}."
    elif score2 > score1:
        reason_str = ", ".join(reasons2)
        return f"{name2} wygląda zdrowiej: {reason_str}."
    else:
        reason_str = ", ".join(reasons1)
        return f"Oba repozytoria mają porównywalne wskaźniki zdrowia. {name1}: {reason_str}."


def main():
    if len(sys.argv) < 3:
        print("Użycie: python compare_repos.py <owner/repo1> <owner/repo2>")
        print("Przykład: python compare_repos.py psf/requests encode/httpx")
        sys.exit(1)

    repo1 = sys.argv[1]
    repo2 = sys.argv[2]
    headers = get_headers()

    print(f"Pobieranie danych dla {repo1} i {repo2}...")

    info1 = get_repo_info(repo1, headers)
    issues1 = analyze_issues(repo1, headers)
    prs1 = analyze_pull_requests(repo1, headers)
    activity1 = analyze_activity(repo1, headers)

    info2 = get_repo_info(repo2, headers)
    issues2 = analyze_issues(repo2, headers)
    prs2 = analyze_pull_requests(repo2, headers)
    activity2 = analyze_activity(repo2, headers)

    print_comparison(repo1, repo2, info1, info2, issues1, issues2, prs1, prs2, activity1, activity2)


if __name__ == "__main__":
    main()
