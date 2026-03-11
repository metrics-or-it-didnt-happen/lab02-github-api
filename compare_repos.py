#!/usr/bin/env python3
"""compare_repos.py - side-by-side comparison of two GitHub repositories."""

import sys

# Re-use all analysis functions from github_profiler
from github_profiler import (
    get_headers,
    get_repo_info,
    analyze_issues,
    analyze_pull_requests,
    analyze_activity,
)


def fmt(value, suffix="") -> str:
    """Format a value for display."""
    if value is None:
        return "N/A"
    if isinstance(value, int):
        return f"{value:,}{suffix}"
    return f"{value}{suffix}"


def verdict(r1: dict, r2: dict, i1: dict, i2: dict,
            p1: dict, p2: dict, a1: dict, a2: dict,
            name1: str, name2: str) -> str:
    """Generate a simple health verdict."""
    scores = {name1: 0, name2: 0}

    if r1["stargazers_count"] > r2["stargazers_count"]:
        scores[name1] += 1
    else:
        scores[name2] += 1

    if i1["closed_pct"] >= i2["closed_pct"]:
        scores[name1] += 1
    else:
        scores[name2] += 1

    t1, t2 = i1.get("avg_response_days"), i2.get("avg_response_days")
    if t1 is not None and t2 is not None:
        if t1 <= t2:
            scores[name1] += 1
        else:
            scores[name2] += 1

    if p1["merged_pct"] >= p2["merged_pct"]:
        scores[name1] += 1
    else:
        scores[name2] += 1

    m1, m2 = p1.get("avg_merge_days"), p2.get("avg_merge_days")
    if m1 is not None and m2 is not None:
        if m1 <= m2:
            scores[name1] += 1
        else:
            scores[name2] += 1

    if a1["recent_commits"] >= a2["recent_commits"]:
        scores[name1] += 1
    else:
        scores[name2] += 1

    winner = max(scores, key=lambda k: scores[k])

    reasons = []
    if i1["closed_pct"] != i2["closed_pct"]:
        better = name1 if i1["closed_pct"] > i2["closed_pct"] else name2
        reasons.append(f"{better} ma wyższy % zamkniętych issues")
    if t1 and t2 and t1 != t2:
        better = name1 if t1 < t2 else name2
        reasons.append(f"{better} szybciej odpowiada na issues")
    if a1["recent_commits"] != a2["recent_commits"]:
        better = name1 if a1["recent_commits"] > a2["recent_commits"] else name2
        reasons.append(f"{better} ma więcej commitów w ostatnim miesiącu")

    reason_str = "; ".join(reasons[:2]) if reasons else "ogólna ocena metryk"
    return f"{winner} wygląda zdrowiej ({reason_str})."


def main():
    if len(sys.argv) < 3:
        print("Użycie: python compare_repos.py <owner/repo1> <owner/repo2>")
        print("Przykład: python compare_repos.py psf/requests encode/httpx")
        sys.exit(1)

    repo1, repo2 = sys.argv[1], sys.argv[2]
    headers = get_headers()

    print(f"Pobieram dane dla {repo1}...")
    r1 = get_repo_info(repo1, headers)
    i1 = analyze_issues(repo1, headers)
    p1 = analyze_pull_requests(repo1, headers)
    a1 = analyze_activity(repo1, headers)

    print(f"Pobieram dane dla {repo2}...")
    r2 = get_repo_info(repo2, headers)
    i2 = analyze_issues(repo2, headers)
    p2 = analyze_pull_requests(repo2, headers)
    a2 = analyze_activity(repo2, headers)

    n1 = repo1.split("/")[-1]
    n2 = repo2.split("/")[-1]

    col = 24
    w = 16

    sep = "-" * (col + w * 2)
    header_sep = "=" * (col + w * 2)

    print(f"\nPORÓWNANIE: {repo1} vs {repo2}")
    print(header_sep)
    print(f"{'Metryka':<{col}}{n1:>{w}}{n2:>{w}}")
    print(sep)

    rows = [
        ("Gwiazdki",              fmt(r1["stargazers_count"]),          fmt(r2["stargazers_count"])),
        ("Forki",                 fmt(r1["forks_count"]),               fmt(r2["forks_count"])),
        ("Otwarte issues",        fmt(r1["open_issues_count"]),         fmt(r2["open_issues_count"])),
        ("% zamkniętych issues",  fmt(i1["closed_pct"], "%"),           fmt(i2["closed_pct"], "%")),
        ("Śr. czas odpowiedzi",   fmt(i1.get("avg_response_days"), " dni"), fmt(i2.get("avg_response_days"), " dni")),
        ("% zmergowanych PR",     fmt(p1["merged_pct"], "%"),           fmt(p2["merged_pct"], "%")),
        ("Śr. czas merge",        fmt(p1.get("avg_merge_days"), " dni"),fmt(p2.get("avg_merge_days"), " dni")),
        ("Commitów (ost. miesiąc)",fmt(a1["recent_commits"]),           fmt(a2["recent_commits"])),
        ("Kontrybutorzy",         fmt(a1["total_contributors"]),        fmt(a2["total_contributors"])),
    ]

    for label, v1, v2 in rows:
        print(f"{label:<{col}}{v1:>{w}}{v2:>{w}}")

    print(sep)
    v = verdict(r1, r2, i1, i2, p1, p2, a1, a2, n1, n2)
    print(f"\nVerdict: {v}\n")


if __name__ == "__main__":
    main()