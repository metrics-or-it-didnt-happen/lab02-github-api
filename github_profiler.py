#!/usr/bin/env python3
"""GitHub Profiler - repository health analysis via GitHub API."""

import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

GITHUB_API = "https://api.github.com"

load_dotenv()


def get_token() -> str:
    """Return a GitHub token from env, .env, or gh CLI."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    # Fallback: gh CLI
    if shutil.which("gh"):
        result = subprocess.run(
            ["gh", "auth", "token"], capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    print("Error: GITHUB_TOKEN not set and gh CLI not available.")
    sys.exit(1)


def get_headers() -> dict[str, str]:
    """Return auth headers for GitHub API."""
    return {"Authorization": f"token {get_token()}"}


def fetch_paginated(
    url: str, headers: dict[str, str], params: dict[str, Any] | None = None, max_items: int = 100
) -> list[Any]:
    """Fetch paginated results from GitHub API."""
    items: list[Any] = []
    params = params or {}
    params.setdefault("per_page", min(max_items, 100))

    while url and len(items) < max_items:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        items.extend(response.json())
        params = {}  # params only for first request

        link_header = response.headers.get("Link", "")
        url = ""
        for part in link_header.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip(" <>")

    return items[:max_items]


def get_repo_info(owner_repo: str, headers: dict[str, str]) -> dict[str, Any]:
    """Fetch basic repository information."""
    r = requests.get(f"{GITHUB_API}/repos/{owner_repo}", headers=headers)
    r.raise_for_status()
    return r.json()


def parse_dt(iso_str: str) -> datetime:
    """Parse ISO 8601 datetime string."""
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))


def analyze_issues(
    owner_repo: str, headers: dict[str, str], repo_info: dict[str, Any], count: int = 100
) -> dict[str, Any]:
    """Analyze recent issues: response time, close rate, top labels."""
    if not repo_info.get("has_issues", True):
        return {"total": 0, "disabled": True}

    raw = fetch_paginated(
        f"{GITHUB_API}/repos/{owner_repo}/issues",
        headers,
        params={"state": "all", "sort": "created", "direction": "desc"},
        max_items=count + 50,  # fetch extra since PRs are mixed in
    )
    # Filter out pull requests
    issues = [i for i in raw if "pull_request" not in i][:count]

    if not issues:
        return {"total": 0}

    closed = [i for i in issues if i["state"] == "closed"]
    open_issues = [i for i in issues if i["state"] == "open"]

    # Top labels
    label_counter: Counter[str] = Counter()
    for issue in issues:
        for label in issue.get("labels", []):
            label_counter[label["name"]] += 1

    # Average time to first response (sample up to 20 issues to avoid rate limit)
    response_times: list[float] = []
    sample = issues[:20]
    for issue in sample:
        if issue["comments"] == 0:
            continue
        comments_url = issue["comments_url"]
        r = requests.get(
            comments_url, headers=headers, params={"per_page": 1}
        )
        if r.status_code == 200:
            comments = r.json()
            if comments:
                created = parse_dt(issue["created_at"])
                first_comment = parse_dt(comments[0]["created_at"])
                delta = (first_comment - created).total_seconds()
                if delta >= 0:
                    response_times.append(delta)

    avg_response_days = None
    if response_times:
        avg_response_days = (sum(response_times) / len(response_times)) / 86400

    return {
        "total": len(issues),
        "closed": len(closed),
        "open": len(open_issues),
        "close_pct": len(closed) / len(issues) * 100,
        "avg_response_days": avg_response_days,
        "top_labels": label_counter.most_common(5),
    }


def analyze_pull_requests(
    owner_repo: str, headers: dict[str, str], repo_info: dict[str, Any], count: int = 50
) -> dict[str, Any]:
    """Analyze recent pull requests: merge time, merge rate."""
    if not repo_info.get("has_pull_requests", True):
        return {"total": 0, "disabled": True}

    prs = fetch_paginated(
        f"{GITHUB_API}/repos/{owner_repo}/pulls",
        headers,
        params={"state": "all", "sort": "created", "direction": "desc"},
        max_items=count,
    )

    if not prs:
        return {"total": 0}

    merged = [p for p in prs if p.get("merged_at")]
    closed_not_merged = [
        p for p in prs if p["state"] == "closed" and not p.get("merged_at")
    ]
    open_prs = [p for p in prs if p["state"] == "open"]

    merge_times: list[float] = []
    for pr in merged:
        created = parse_dt(pr["created_at"])
        merged_at = parse_dt(pr["merged_at"])
        delta = (merged_at - created).total_seconds() / 86400
        merge_times.append(delta)

    avg_merge_days = sum(merge_times) / len(merge_times) if merge_times else None

    return {
        "total": len(prs),
        "merged": len(merged),
        "rejected": len(closed_not_merged),
        "open": len(open_prs),
        "merged_pct": len(merged) / len(prs) * 100,
        "rejected_pct": len(closed_not_merged) / len(prs) * 100,
        "open_pct": len(open_prs) / len(prs) * 100,
        "avg_merge_days": avg_merge_days,
    }


def analyze_activity(owner_repo: str, headers: dict[str, str]) -> dict[str, Any]:
    """Compare recent commit activity with a year ago."""
    now = datetime.now(timezone.utc)

    # Last month
    since_recent = (now - timedelta(days=30)).isoformat()
    until_recent = now.isoformat()

    # Same month a year ago
    since_year_ago = (now - timedelta(days=395)).isoformat()
    until_year_ago = (now - timedelta(days=365)).isoformat()

    recent = fetch_paginated(
        f"{GITHUB_API}/repos/{owner_repo}/commits",
        headers,
        params={"since": since_recent, "until": until_recent},
        max_items=300,
    )

    year_ago = fetch_paginated(
        f"{GITHUB_API}/repos/{owner_repo}/commits",
        headers,
        params={"since": since_year_ago, "until": until_year_ago},
        max_items=300,
    )

    # Unique contributors (from contributor stats endpoint)
    r = requests.get(
        f"{GITHUB_API}/repos/{owner_repo}/contributors",
        headers=headers,
        params={"per_page": 1, "anon": "true"},
    )
    total_contributors = None
    if r.status_code == 200:
        # Parse last page from Link header to get total count
        link = r.headers.get("Link", "")
        for part in link.split(","):
            if 'rel="last"' in part:
                import re

                match = re.search(r"[?&]page=(\d+)", part)
                if match:
                    total_contributors = int(match.group(1))
        if total_contributors is None and r.json():
            total_contributors = len(r.json())

    recent_count = len(recent)
    year_ago_count = len(year_ago)

    trend = None
    if year_ago_count > 0:
        trend = ((recent_count - year_ago_count) / year_ago_count) * 100

    return {
        "recent_commits": recent_count,
        "year_ago_commits": year_ago_count,
        "trend_pct": trend,
        "total_contributors": total_contributors,
    }


def format_report(
    repo_info: dict[str, Any], issues: dict[str, Any], prs: dict[str, Any], activity: dict[str, Any]
) -> str:
    """Format the complete report as a string."""
    lines: list[str] = []
    lines.append(f"{'=' * 60}")
    lines.append(f"REPOSITORY PROFILE: {repo_info['full_name']}")
    lines.append(f"{'=' * 60}")

    # Basic metrics
    lines.append(f"\n--- Basic Metrics ---")
    lines.append(f"  Stars:          {repo_info['stargazers_count']:,}")
    lines.append(f"  Forks:          {repo_info['forks_count']:,}")
    lines.append(f"  Open issues:    {repo_info['open_issues_count']:,}")
    lines.append(f"  Watchers:       {repo_info['subscribers_count']:,}")
    lines.append(f"  Language:       {repo_info.get('language', 'N/A')}")
    lic: dict[str, Any] = repo_info.get("license") or {}
    lines.append(f"  License:        {lic.get('spdx_id', 'N/A')}")

    # Issues
    lines.append(f"\n--- Issues (last {issues.get('total', 0)}) ---")
    if not repo_info.get("has_issues", True):
        lines.append("  Issues are disabled on this repository.")
    elif issues.get("total", 0) > 0:
        lines.append(f"  Closed:                      {issues['close_pct']:.0f}%")
        if issues["avg_response_days"] is not None:
            lines.append(
                f"  Avg time to first response:  {issues['avg_response_days']:.1f} days"
            )
        else:
            lines.append(f"  Avg time to first response:  N/A")
        if issues["top_labels"]:
            labels_str = ", ".join(
                f"{name} ({cnt})" for name, cnt in issues["top_labels"]
            )
            lines.append(f"  Top labels:                  {labels_str}")
    else:
        lines.append(f"  No issues found.")

    # Pull Requests
    lines.append(f"\n--- Pull Requests (last {prs.get('total', 0)}) ---")
    if not repo_info.get("has_pull_requests", True):
        lines.append("  Pull requests are disabled on this repository.")
    elif prs.get("total", 0) > 0:
        lines.append(f"  Merged:                      {prs['merged_pct']:.0f}%")
        lines.append(f"  Rejected:                    {prs['rejected_pct']:.0f}%")
        lines.append(f"  Open:                        {prs['open_pct']:.0f}%")
        if prs["avg_merge_days"] is not None:
            lines.append(
                f"  Avg time to merge:           {prs['avg_merge_days']:.1f} days"
            )
    else:
        lines.append(f"  No pull requests found.")

    # Activity
    lines.append(f"\n--- Activity ---")
    lines.append(f"  Commits (last 30 days):      {activity['recent_commits']}")
    lines.append(f"  Commits (year ago, 30 days): {activity['year_ago_commits']}")
    if activity["trend_pct"] is not None:
        direction = "up" if activity["trend_pct"] >= 0 else "down"
        lines.append(
            f"  Trend:                       {direction} {abs(activity['trend_pct']):.0f}%"
        )
    else:
        lines.append(f"  Trend:                       N/A (no commits year ago)")
    if activity["total_contributors"] is not None:
        lines.append(
            f"  Total contributors:          {activity['total_contributors']:,}"
        )

    return "\n".join(lines)


def compare_repos(repo1: str, repo2: str, headers: dict[str, str]) -> str:
    """Generate a side-by-side comparison of two repositories."""
    print(f"Profiling {repo1}...")
    info1 = get_repo_info(repo1, headers)
    issues1 = analyze_issues(repo1, headers, info1)
    prs1 = analyze_pull_requests(repo1, headers, info1)
    act1 = analyze_activity(repo1, headers)

    print(f"Profiling {repo2}...")
    info2 = get_repo_info(repo2, headers)
    issues2 = analyze_issues(repo2, headers, info2)
    prs2 = analyze_pull_requests(repo2, headers, info2)
    act2 = analyze_activity(repo2, headers)

    w = 24  # metric column width
    v = 16  # value column width
    lines: list[str] = []
    lines.append(f"COMPARISON: {repo1} vs {repo2}")
    lines.append("=" * 60)
    lines.append(f"{'Metric':<{w}} {repo1.split('/')[-1]:>{v}} {repo2.split('/')[-1]:>{v}}")
    lines.append("-" * 60)

    def row(label: str, v1: object, v2: object) -> None:
        lines.append(f"{label:<{w}} {str(v1):>{v}} {str(v2):>{v}}")

    row("Stars", f"{info1['stargazers_count']:,}", f"{info2['stargazers_count']:,}")
    row("Forks", f"{info1['forks_count']:,}", f"{info2['forks_count']:,}")
    row("Open issues", f"{info1['open_issues_count']:,}", f"{info2['open_issues_count']:,}")

    def issue_val(iss: dict[str, Any], key: str, fmt: str = "") -> str:
        if iss.get("disabled"):
            return "disabled"
        if not iss.get("total"):
            return "N/A"
        val = iss.get(key)
        if val is None:
            return "N/A"
        return f"{val:{fmt}}" if fmt else str(val)

    def pr_val(pr: dict[str, Any], key: str, fmt: str = "") -> str:
        if pr.get("disabled"):
            return "disabled"
        if not pr.get("total"):
            return "N/A"
        val = pr.get(key)
        if val is None:
            return "N/A"
        return f"{val:{fmt}}" if fmt else str(val)

    row("Issues", issue_val(issues1, "total"), issue_val(issues2, "total"))
    row("% closed issues", issue_val(issues1, "close_pct", ".0f") + "%" if issues1.get("close_pct") else issue_val(issues1, "close_pct"), issue_val(issues2, "close_pct", ".0f") + "%" if issues2.get("close_pct") else issue_val(issues2, "close_pct"))
    r1 = f"{issues1['avg_response_days']:.1f} days" if issues1.get("avg_response_days") else issue_val(issues1, "avg_response_days")
    r2 = f"{issues2['avg_response_days']:.1f} days" if issues2.get("avg_response_days") else issue_val(issues2, "avg_response_days")
    row("Avg response time", r1, r2)

    row("PRs", pr_val(prs1, "total"), pr_val(prs2, "total"))
    row("% merged PRs", pr_val(prs1, "merged_pct", ".0f") + "%" if prs1.get("merged_pct") else pr_val(prs1, "merged_pct"), pr_val(prs2, "merged_pct", ".0f") + "%" if prs2.get("merged_pct") else pr_val(prs2, "merged_pct"))
    m1 = f"{prs1['avg_merge_days']:.1f} days" if prs1.get("avg_merge_days") else pr_val(prs1, "avg_merge_days")
    m2 = f"{prs2['avg_merge_days']:.1f} days" if prs2.get("avg_merge_days") else pr_val(prs2, "avg_merge_days")
    row("Avg merge time", m1, m2)

    row("Commits (last month)", act1["recent_commits"], act2["recent_commits"])

    # Verdict
    score1, score2 = 0, 0
    if issues1.get("close_pct", 0) > issues2.get("close_pct", 0):
        score1 += 1
    else:
        score2 += 1
    if (issues1.get("avg_response_days") or 999) < (issues2.get("avg_response_days") or 999):
        score1 += 1
    else:
        score2 += 1
    if prs1.get("merged_pct", 0) > prs2.get("merged_pct", 0):
        score1 += 1
    else:
        score2 += 1
    if act1["recent_commits"] > act2["recent_commits"]:
        score1 += 1
    else:
        score2 += 1

    winner = repo1.split("/")[-1] if score1 > score2 else repo2.split("/")[-1]
    lines.append("")
    lines.append(
        f"Verdict: {winner} appears healthier and more active ({max(score1, score2)}/{score1 + score2} metrics)."
    )

    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python github_profiler.py <owner/repo> [owner/repo2]")
        print("  Single repo:  python github_profiler.py django/django")
        print("  Compare:      python github_profiler.py psf/requests encode/httpx")
        sys.exit(1)

    headers = get_headers()

    if len(sys.argv) >= 3:
        # Compare mode
        report = compare_repos(sys.argv[1], sys.argv[2], headers)
        print(report)
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        (output_dir / "comparison.txt").write_text(report)
        print(f"\nReport saved to output/comparison.txt")
    else:
        # Single repo mode
        owner_repo = sys.argv[1]
        print(f"Profiling {owner_repo}...")

        repo_info = get_repo_info(owner_repo, headers)
        issues = analyze_issues(owner_repo, headers, repo_info)
        prs = analyze_pull_requests(owner_repo, headers, repo_info)
        activity = analyze_activity(owner_repo, headers)

        report = format_report(repo_info, issues, prs, activity)
        print(report)

        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        (output_dir / "report.txt").write_text(report)
        print(f"\nReport saved to output/report.txt")


if __name__ == "__main__":
    main()
