#!/usr/bin/env python3
"""Compare two GitHub repositories side-by-side."""

import sys

from github_profiler import (
    get_headers,
    get_repo_info,
    analyze_issues,
    analyze_pull_requests,
    analyze_activity,
)


def _fmt(val) -> str:
    """Format value for table display."""
    if val is None:
        return "N/A"
    if isinstance(val, int):
        return f"{val:,}"
    return str(val)


def print_comparison(name1: str, name2: str, repo1: dict, repo2: dict,
                     issues1: dict, issues2: dict, prs1: dict, prs2: dict,
                     activity1: dict, activity2: dict) -> None:
    """Print side-by-side comparison table."""
    col_width = 22
    metric_width = 25

    def row(metric: str, v1, v2: str) -> None:
        m = metric.ljust(metric_width)
        a = _fmt(v1).rjust(col_width)
        b = _fmt(v2).rjust(col_width)
        print(f"{m} {a}  {b}")

    print(f"\nPORÓWNANIE: {name1} vs {name2}")
    print("=" * 60)
    print(f"{'Metryka':<{metric_width}} {name1.split('/')[-1]:>{col_width}}  {name2.split('/')[-1]:>{col_width}}")
    print("-" * 60)

    row("Gwiazdki", repo1["stargazers_count"], repo2["stargazers_count"])
    row("Forki", repo1["forks_count"], repo2["forks_count"])
    row("Otwarte issues", repo1["open_issues_count"], repo2["open_issues_count"])
    row("% zamkniętych issues", f"{issues1['closed_pct']}%", f"{issues2['closed_pct']}%")

    resp1 = f"{issues1['avg_response_days']} dni" if issues1.get("avg_response_days") else "N/A"
    resp2 = f"{issues2['avg_response_days']} dni" if issues2.get("avg_response_days") else "N/A"
    row("Śr. czas odpowiedzi", resp1, resp2)

    row("% zmergowanych PR", f"{prs1['merged_pct']}%", f"{prs2['merged_pct']}%")

    merge1 = f"{prs1['avg_merge_days']} dni" if prs1.get("avg_merge_days") else "N/A"
    merge2 = f"{prs2['avg_merge_days']} dni" if prs2.get("avg_merge_days") else "N/A"
    row("Śr. czas merge", merge1, merge2)

    row("Commitów (ost. miesiąc)", activity1["commits_this_month"], activity2["commits_this_month"])


def verdict(name1: str, name2: str, repo1: dict, repo2: dict,
            issues1: dict, issues2: dict, prs1: dict, prs2: dict,
            activity1: dict, activity2: dict) -> str:
    """Generate simple verdict on which repo looks healthier."""
    short1 = name1.split("/")[-1]
    short2 = name2.split("/")[-1]

    reasons1 = []
    reasons2 = []

    # Fewer open issues = healthier
    if repo1["open_issues_count"] < repo2["open_issues_count"]:
        reasons1.append("ma mniej otwartych issues")
    elif repo2["open_issues_count"] < repo1["open_issues_count"]:
        reasons2.append("ma mniej otwartych issues")

    # Higher % closed issues = better maintenance
    if issues1["closed_pct"] > issues2["closed_pct"]:
        reasons1.append("ma wyższy % zamkniętych issues")
    elif issues2["closed_pct"] > issues1["closed_pct"]:
        reasons2.append("ma wyższy % zamkniętych issues")

    # Faster response time = more responsive
    r1, r2 = issues1.get("avg_response_days"), issues2.get("avg_response_days")
    if r1 is not None and r2 is not None:
        if r1 < r2:
            reasons1.append("szybciej reaguje na issues")
        elif r2 < r1:
            reasons2.append("szybciej reaguje na issues")

    # Higher % merged PRs = healthier PR flow
    if prs1["merged_pct"] > prs2["merged_pct"]:
        reasons1.append("ma wyższy % zmergowanych PR")
    elif prs2["merged_pct"] > prs1["merged_pct"]:
        reasons2.append("ma wyższy % zmergowanych PR")

    # More commits = more active
    if activity1["commits_this_month"] > activity2["commits_this_month"]:
        reasons1.append("jest aktywniej rozwijane")
    elif activity2["commits_this_month"] > activity1["commits_this_month"]:
        reasons2.append("jest aktywniej rozwijane")

    if len(reasons1) > len(reasons2):
        winner = short1
        reasons = reasons1
    elif len(reasons2) > len(reasons1):
        winner = short2
        reasons = reasons2
    else:
        return "Verdict: Oba repozytoria wypadają podobnie pod względem zdrowia."

    reason_str = " i ".join(reasons)
    return f"Verdict: {winner} wygląda zdrowiej — {reason_str}."


def main():
    if len(sys.argv) < 3:
        print("Użycie: python compare_repos.py <owner/repo1> <owner/repo2>")
        print("Przykład: python compare_repos.py psf/requests encode/httpx")
        sys.exit(1)

    repo1_name = sys.argv[1]
    repo2_name = sys.argv[2]
    headers = get_headers()

    print(f"Porównuję {repo1_name} i {repo2_name}...")

    repo1 = get_repo_info(repo1_name, headers)
    repo2 = get_repo_info(repo2_name, headers)

    print(f"  Pobieram dane o issues...")
    issues1 = analyze_issues(repo1_name, headers)
    issues2 = analyze_issues(repo2_name, headers)

    print(f"  Pobieram dane o PR...")
    prs1 = analyze_pull_requests(repo1_name, headers)
    prs2 = analyze_pull_requests(repo2_name, headers)

    print(f"  Pobieram dane o aktywności...")
    activity1 = analyze_activity(repo1_name, headers)
    activity2 = analyze_activity(repo2_name, headers)

    print_comparison(
        repo1_name, repo2_name,
        repo1, repo2,
        issues1, issues2,
        prs1, prs2,
        activity1, activity2,
    )

    v = verdict(
        repo1_name, repo2_name,
        repo1, repo2,
        issues1, issues2,
        prs1, prs2,
        activity1, activity2,
    )
    print(f"\n{v}")


if __name__ == "__main__":
    main()
