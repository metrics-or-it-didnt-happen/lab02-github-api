#!/usr/bin/env python3
"""GitHub Profiler - repository health analysis via GitHub API."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from github import Auth, Github
from github.Issue import Issue
from github.Repository import Repository

load_dotenv()


def get_token() -> str:
    """Return a GitHub token from env, .env, or gh CLI."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    if shutil.which("gh"):
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    print("Error: GITHUB_TOKEN not set and gh CLI not available.")
    sys.exit(1)


@dataclass
class RepoCounts:
    """Exact issue/PR counts from GraphQL API."""

    issues_total: int = 0
    issues_open: int = 0
    prs_total: int = 0
    prs_open: int = 0


def fetch_repo_counts(owner: str, name: str, token: str) -> RepoCounts:
    """Fetch exact issue/PR counts via GraphQL (no 1000 cap)."""
    query = """
    query($owner: String!, $name: String!) {
      repository(owner: $owner, name: $name) {
        issues { totalCount }
        openIssues: issues(states: OPEN) { totalCount }
        pullRequests { totalCount }
        openPRs: pullRequests(states: OPEN) { totalCount }
      }
    }
    """
    payload = json.dumps({"query": query, "variables": {"owner": owner, "name": name}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())["data"]["repository"]
    return RepoCounts(
        issues_total=data["issues"]["totalCount"],
        issues_open=data["openIssues"]["totalCount"],
        prs_total=data["pullRequests"]["totalCount"],
        prs_open=data["openPRs"]["totalCount"],
    )


@dataclass
class IssueStats:
    total: int = 0
    closed: int = 0
    open: int = 0
    close_pct: float = 0.0
    avg_response_days: float | None = None
    top_labels: list[tuple[str, int]] = field(default_factory=list[tuple[str, int]])
    disabled: bool = False


@dataclass
class PRStats:
    total: int = 0
    merged: int = 0
    rejected: int = 0
    open: int = 0
    merged_pct: float = 0.0
    rejected_pct: float = 0.0
    open_pct: float = 0.0
    avg_merge_days: float | None = None
    disabled: bool = False


@dataclass
class ActivityStats:
    recent_commits: int = 0
    year_ago_commits: int = 0
    trend_pct: float | None = None
    total_contributors: int | None = None


def analyze_issues(repo: Repository, counts: RepoCounts, count: int = 100) -> IssueStats:
    """Analyze recent issues: response time, close rate, top labels."""
    if not repo.has_issues:
        return IssueStats(disabled=True)

    if counts.issues_total == 0:
        return IssueStats()

    # Sample recent issues for label/response analysis
    raw_issues = repo.get_issues(state="all", sort="created", direction="desc")
    issues: list[Issue] = []
    for item in raw_issues:
        if item.pull_request is None:
            issues.append(item)
        if len(issues) >= count:
            break

    label_counter: Counter[str] = Counter()
    for issue in issues:
        for label in issue.labels:
            label_counter[label.name] += 1

    response_times: list[float] = []
    for issue in issues[:20]:
        if issue.comments == 0:
            continue
        comments = issue.get_comments()
        if comments.totalCount == 0:
            continue
        first = comments[0]
        delta = (first.created_at - issue.created_at).total_seconds()
        if delta >= 0:
            response_times.append(delta)

    avg_response = None
    if response_times:
        avg_response = (sum(response_times) / len(response_times)) / 86400

    return IssueStats(
        total=counts.issues_total,
        closed=counts.issues_total - counts.issues_open,
        open=counts.issues_open,
        close_pct=(counts.issues_total - counts.issues_open) / counts.issues_total * 100,
        avg_response_days=avg_response,
        top_labels=label_counter.most_common(5),
    )


def analyze_pull_requests(repo: Repository, counts: RepoCounts, count: int = 50) -> PRStats:
    """Analyze recent pull requests: merge time, merge rate."""
    if not repo.raw_data.get("has_pull_requests", True):
        return PRStats(disabled=True)

    if counts.prs_total == 0:
        return PRStats()

    # Sample recent PRs for merge time analysis
    raw_prs = repo.get_pulls(state="all", sort="created", direction="desc")
    prs = [raw_prs[i] for i in range(min(count, raw_prs.totalCount))]

    merged = [p for p in prs if p.merged_at]
    rejected = [p for p in prs if p.state == "closed" and not p.merged_at]
    open_prs = [p for p in prs if p.state == "open"]

    merge_times: list[float] = []
    for pr in merged:
        assert pr.merged_at is not None  # guaranteed by filter above
        merge_times.append((pr.merged_at - pr.created_at).total_seconds() / 86400)

    avg_merge = sum(merge_times) / len(merge_times) if merge_times else None
    n = len(prs)

    return PRStats(
        total=counts.prs_total,
        merged=len(merged),
        rejected=len(rejected),
        open=counts.prs_open,
        merged_pct=len(merged) / n * 100 if n else 0,
        rejected_pct=len(rejected) / n * 100 if n else 0,
        open_pct=len(open_prs) / n * 100 if n else 0,
        avg_merge_days=avg_merge,
    )


def analyze_activity(repo: Repository) -> ActivityStats:
    """Compare recent commit activity with a year ago."""
    now = datetime.now(timezone.utc)

    since_recent = now - timedelta(days=30)
    since_year_ago = now - timedelta(days=395)
    until_year_ago = now - timedelta(days=365)

    recent = repo.get_commits(since=since_recent, until=now)
    year_ago = repo.get_commits(since=since_year_ago, until=until_year_ago)

    recent_count = min(recent.totalCount, 300)
    year_ago_count = min(year_ago.totalCount, 300)

    contributors = repo.get_contributors(anon="true")
    total_contributors = contributors.totalCount

    trend = None
    if year_ago_count > 0:
        trend = ((recent_count - year_ago_count) / year_ago_count) * 100

    return ActivityStats(
        recent_commits=recent_count,
        year_ago_commits=year_ago_count,
        trend_pct=trend,
        total_contributors=total_contributors,
    )


def format_report(
    repo: Repository, issues: IssueStats, prs: PRStats, activity: ActivityStats
) -> str:
    """Format the complete report as a string."""
    lines: list[str] = []
    lines.append(f"{'=' * 60}")
    lines.append(f"REPOSITORY PROFILE: {repo.full_name}")
    lines.append(f"{'=' * 60}")

    lines.append("\n--- Basic Metrics ---")
    lines.append(f"  Stars:          {repo.stargazers_count:,}")
    lines.append(f"  Forks:          {repo.forks_count:,}")
    lines.append(f"  Open issues:    {issues.open:,}" if not issues.disabled else "  Open issues:    N/A (disabled)")
    lines.append(f"  Open PRs:       {prs.open:,}" if not prs.disabled else "  Open PRs:       N/A (disabled)")
    lines.append(f"  Watchers:       {repo.subscribers_count:,}")
    lines.append(f"  Language:       {repo.language or 'N/A'}")
    lic = repo.license
    lines.append(f"  License:        {lic.spdx_id if lic else 'N/A'}")

    # Issues
    lines.append(f"\n--- Issues ({issues.open:,}/{issues.total - issues.open:,}) ---")
    if issues.disabled:
        lines.append("  Issues are disabled on this repository.")
    elif issues.total > 0:
        lines.append(f"  Closed:                      {issues.close_pct:.0f}%")
        if issues.avg_response_days is not None:
            lines.append(
                f"  Avg time to first response:  {issues.avg_response_days:.1f} days"
            )
        else:
            lines.append("  Avg time to first response:  N/A")
        if issues.top_labels:
            labels_str = ", ".join(f"{name} ({cnt})" for name, cnt in issues.top_labels)
            lines.append(f"  Top labels:                  {labels_str}")
    else:
        lines.append("  No issues found.")

    # Pull Requests
    lines.append(f"\n--- Pull Requests ({prs.open:,}/{prs.total - prs.open:,}) ---")
    if prs.disabled:
        lines.append("  Pull requests are disabled on this repository.")
    elif prs.total > 0:
        lines.append(f"  Merged:                      {prs.merged_pct:.0f}%")
        lines.append(f"  Rejected:                    {prs.rejected_pct:.0f}%")
        lines.append(f"  Open:                        {prs.open_pct:.0f}%")
        if prs.avg_merge_days is not None:
            lines.append(
                f"  Avg time to merge:           {prs.avg_merge_days:.1f} days"
            )
    else:
        lines.append("  No pull requests found.")

    # Activity
    lines.append("\n--- Activity ---")
    lines.append(f"  Commits (last 30 days):      {activity.recent_commits}")
    lines.append(f"  Commits (year ago, 30 days): {activity.year_ago_commits}")
    if activity.trend_pct is not None:
        direction = "up" if activity.trend_pct >= 0 else "down"
        lines.append(
            f"  Trend:                       {direction} {abs(activity.trend_pct):.0f}%"
        )
    else:
        lines.append("  Trend:                       N/A (no commits year ago)")
    if activity.total_contributors is not None:
        lines.append(f"  Total contributors:          {activity.total_contributors:,}")

    return "\n".join(lines)


def fmt_stat(
    val: float | int | None, disabled: bool, fmt: str = "", suffix: str = ""
) -> str:
    """Format a stat value, handling disabled/N/A cases."""
    if disabled:
        return "disabled"
    if val is None or val == 0:
        return "N/A"
    return f"{val:{fmt}}{suffix}" if fmt else f"{val}{suffix}"


def compare_repos(repo1: Repository, repo2: Repository, token: str) -> str:
    """Generate a side-by-side comparison of two repositories."""
    owner1, name1_ = repo1.full_name.split("/")
    owner2, name2_ = repo2.full_name.split("/")

    print(f"Profiling {repo1.full_name}...")
    counts1 = fetch_repo_counts(owner1, name1_, token)
    issues1 = analyze_issues(repo1, counts1)
    prs1 = analyze_pull_requests(repo1, counts1)
    act1 = analyze_activity(repo1)

    print(f"Profiling {repo2.full_name}...")
    counts2 = fetch_repo_counts(owner2, name2_, token)
    issues2 = analyze_issues(repo2, counts2)
    prs2 = analyze_pull_requests(repo2, counts2)
    act2 = analyze_activity(repo2)

    w = 24
    v = 16
    lines: list[str] = []
    name1 = repo1.name
    name2 = repo2.name
    lines.append(f"COMPARISON: {repo1.full_name} vs {repo2.full_name}")
    lines.append("=" * 60)
    lines.append(f"{'Metric':<{w}} {name1:>{v}} {name2:>{v}}")
    lines.append("-" * 60)

    def row(label: str, v1: object, v2: object) -> None:
        lines.append(f"{label:<{w}} {str(v1):>{v}} {str(v2):>{v}}")

    row("Stars", f"{repo1.stargazers_count:,}", f"{repo2.stargazers_count:,}")
    row("Forks", f"{repo1.forks_count:,}", f"{repo2.forks_count:,}")

    row(
        "Issues",
        fmt_stat(issues1.total, issues1.disabled),
        fmt_stat(issues2.total, issues2.disabled),
    )
    row(
        "% closed issues",
        fmt_stat(issues1.close_pct, issues1.disabled, ".0f", "%"),
        fmt_stat(issues2.close_pct, issues2.disabled, ".0f", "%"),
    )
    row(
        "Avg response time",
        fmt_stat(issues1.avg_response_days, issues1.disabled, ".1f", " days"),
        fmt_stat(issues2.avg_response_days, issues2.disabled, ".1f", " days"),
    )

    row("PRs", fmt_stat(prs1.total, prs1.disabled), fmt_stat(prs2.total, prs2.disabled))
    row(
        "% merged PRs",
        fmt_stat(prs1.merged_pct, prs1.disabled, ".0f", "%"),
        fmt_stat(prs2.merged_pct, prs2.disabled, ".0f", "%"),
    )
    row(
        "Avg merge time",
        fmt_stat(prs1.avg_merge_days, prs1.disabled, ".1f", " days"),
        fmt_stat(prs2.avg_merge_days, prs2.disabled, ".1f", " days"),
    )

    row("Commits (last month)", act1.recent_commits, act2.recent_commits)

    # Verdict (skip disabled metrics)
    score1, score2 = 0, 0
    if not issues1.disabled and not issues2.disabled:
        if issues1.close_pct > issues2.close_pct:
            score1 += 1
        else:
            score2 += 1
        if (issues1.avg_response_days or 999) < (issues2.avg_response_days or 999):
            score1 += 1
        else:
            score2 += 1
    if not prs1.disabled and not prs2.disabled:
        if prs1.merged_pct > prs2.merged_pct:
            score1 += 1
        else:
            score2 += 1
    if act1.recent_commits > act2.recent_commits:
        score1 += 1
    else:
        score2 += 1

    total = score1 + score2
    if total > 0:
        winner = name1 if score1 > score2 else name2
        lines.append("")
        lines.append(
            f"Verdict: {winner} appears healthier and more active ({max(score1, score2)}/{total} metrics)."
        )

    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python github_profiler.py <owner/repo> [owner/repo2]")
        print("  Single repo:  python github_profiler.py django/django")
        print("  Compare:      python github_profiler.py psf/requests encode/httpx")
        sys.exit(1)

    token = get_token()
    gh = Github(auth=Auth.Token(token))

    if len(sys.argv) >= 3:
        repo1 = gh.get_repo(sys.argv[1])
        repo2 = gh.get_repo(sys.argv[2])
        report = compare_repos(repo1, repo2, token)
        print(report)
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        (output_dir / "comparison.txt").write_text(report)
        print("\nReport saved to output/comparison.txt")
    else:
        repo = gh.get_repo(sys.argv[1])
        print(f"Profiling {repo.full_name}...")

        owner, name = repo.full_name.split("/")
        counts = fetch_repo_counts(owner, name, token)
        issues = analyze_issues(repo, counts)
        prs = analyze_pull_requests(repo, counts)
        activity = analyze_activity(repo)

        report = format_report(repo, issues, prs, activity)
        print(report)

        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)
        (output_dir / "report.txt").write_text(report)
        print("\nReport saved to output/report.txt")


if __name__ == "__main__":
    main()
