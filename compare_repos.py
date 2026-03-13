from github_profiler import *


def print_comparison(
    repo_info: dict,
    issues: dict,
    prs: dict,
    activity: dict,
    repo_info2: dict,
    issues2: dict,
    prs2: dict,
    activity2: dict,
) -> None:
    print(f"\n{'=' * 60}")
    print(f"PORÓWNANIE {repo_info['full_name']} vs {repo_info2['full_name']}")

    print(f"{'=' * 60}")
    print(f"{'Metryka':<25}{'repo1':>15}{'repo2':>15}")
    print(f"{'-' * 60}")
    print(
        f"{'Gwiazdki':<25}{repo_info['stargazers_count']:>15,}{repo_info2['stargazers_count']:>15,}"
    )
    print(
        f"{'Forki':<25}{repo_info['forks_count']:>15,}{repo_info2['forks_count']:>15,}"
    )
    print(
        f"{'Otwarte issues':<25}{repo_info['open_issues_count']:>15,}{repo_info2['open_issues_count']:>15,}"
    )
    print(
        f"{'% zamkniętych issues':<25}{issues['percent_closed']:>14.1f}%{issues2['percent_closed']:>14.1f}%"
    )
    print(
        f"{'Śr. czas odpowiedzi':<25}{issues['ave_response_time']:>12.2f} dni{issues2['ave_response_time']:>12.2f} dni"
    )
    print(
        f"{'% zmergowanych PR':<25}{prs['merged_pct']:>14.0f}%{prs2['merged_pct']:>14.0f}%"
    )
    print(
        f"{'Śr. czas merge':<25}{prs['avg_merge_days']:>12.1f} dni{prs2['avg_merge_days']:>12.1f} dni"
    )
    print(
        f"{'Commitów (ost. miesiąc)':<25}{activity['sum_last_month']:>15}{activity2['sum_last_month']:>15}"
    )

    reason1, reason2 = [], []

    if repo_info["stargazers_count"] > repo_info2["stargazers_count"]:
        reason1.append("Więcej gwiazdek")
    elif repo_info["stargazers_count"] < repo_info2["stargazers_count"]:
        reason2.append("Więcej gwiazdek")

    if repo_info["forks_count"] > repo_info2["forks_count"]:
        reason1.append("Więcej forków")
    elif repo_info["forks_count"] < repo_info2["forks_count"]:
        reason2.append("Więcej forków")

    if repo_info["open_issues_count"] < repo_info2["open_issues_count"]:
        reason1.append("Mniej otwartych issues")
    elif repo_info["open_issues_count"] > repo_info2["open_issues_count"]:
        reason2.append("Mniej otwartych issues")

    if issues["percent_closed"] > issues2["percent_closed"]:
        reason1.append("Wyższy % zamkniętych issues")
    elif issues["percent_closed"] < issues2["percent_closed"]:
        reason2.append("Wyższy % zamkniętych issues")

    if issues["ave_response_time"] < issues2["ave_response_time"]:
        reason1.append("Krótszy czas odpowiedzi na issues")
    elif issues["ave_response_time"] > issues2["ave_response_time"]:
        reason2.append("Krótszy czas odpowiedzi na issues")

    if prs["merged_pct"] > prs2["merged_pct"]:
        reason1.append("Wyższy % zmergowanych PR")
    elif prs["merged_pct"] < prs2["merged_pct"]:
        reason2.append("Wyższy % zmergowanych PR")

    if prs["avg_merge_days"] < prs2["avg_merge_days"]:
        reason1.append("Krótszy czas merge'owania PR")
    elif prs["avg_merge_days"] > prs2["avg_merge_days"]:
        reason2.append("Krótszy czas merge'owania PR")

    if activity["sum_last_month"] > activity2["sum_last_month"]:
        reason1.append("Większa aktywność (commity w ost. miesiącu)")
    elif activity["sum_last_month"] < activity2["sum_last_month"]:
        reason2.append("Większa aktywność (commity w ost. miesiącu)")

    zwyciezca = "Remis"
    reason = []
    if len(reason1) > len(reason2):
        zwyciezca = repo_info["full_name"]
        reason = reason1
    elif len(reason1) < len(reason2):
        zwyciezca = repo_info2["full_name"]
        reason = reason2

    print(f"{'=' * 60}")
    print(f"Werdykt: {zwyciezca}")
    print(f"{'-' * 60}")
    for r in reason:
        print(f"-> {r}")


def compare_repo():
    if len(sys.argv) < 3:
        print("Użycie: python compare_repos.py <owner/repo> <owner/repo2>")
        print("Przykład: python compare_repos.py psf/requests encode/httpx")
        sys.exit(1)

    owner_repo = sys.argv[1]
    owner_repo2 = sys.argv[2]

    headers = get_headers()

    print(f"Porównuję {owner_repo} i {owner_repo2}...")

    repo_info = get_repo_info(owner_repo, headers)
    issues = analyze_issues(owner_repo, headers)
    prs = analyze_pull_requests(owner_repo, headers)
    activity = analyze_activity(owner_repo, headers)

    repo_info2 = get_repo_info(owner_repo2, headers)
    issues2 = analyze_issues(owner_repo2, headers)
    prs2 = analyze_pull_requests(owner_repo2, headers)
    activity2 = analyze_activity(owner_repo2, headers)

    print_comparison(
        repo_info, issues, prs, activity, repo_info2, issues2, prs2, activity2
    )


compare_repo()
