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

def fetch_paginated(url: str, headers: dict, 
                    params: dict | None = None) -> list:
    """Fetch paginated results from GitHub API.
    GitHub API returns max 100 items per page. This function handles
    pagination via the 'Link' header.
    """
    items = []
    params = params or {}
    params.setdefault("per_page", 100)

    # dopóki jest kolejna strona (url)
    while url:
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

    return items

def fetch_issues(url: str, headers: dict, params: dict | None = None,
                max_items: int = 100) -> list:
    """Fetch paginated issues from GitHub API.
    GitHub API returns max 100 items per page. This function handles
    pagination via the 'Link' header. 
    Filters out pull requests.
    """
    items = []
    params = params or {}
    params.setdefault("per_page", min(max_items, 100))

    # dopóki jest kolejna strona (url) i nie osiągnięto max_items
    while url and len(items) < max_items:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()

        issues = response.json()
        issues = [issue for issue in issues if "pull_request" not in issue]
        items.extend(issues)
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
    # zwraca opiekt tylu requests.Response
    r = requests.get(f"{GITHUB_API}/repos/{owner_repo}", headers=headers)
    # sprawdza poprawność wyniku czyli status HTTP odpowiedzi
    r.raise_for_status()
    # zreaca info w formie słownika (JSON)
    return r.json()

def first_comment_time(issue: dict, headers: dict) -> datetime | None:
    """Return datetime of the first comment on an issue,
    or None if no comments."""
    comments_nr = issue["comments"]
    if comments_nr<1:
        return None
    
    comments_url = issue["comments_url"]
    r = requests.get(comments_url, headers=headers)
    r.raise_for_status()
    comments = r.json()

    if comments:
        first_comment = comments[0]
        date = datetime.fromisoformat(first_comment["created_at"].rstrip("Z")).replace(tzinfo=timezone.utc)
        return date
    
    return None

def analyze_issues(owner_repo: str, headers: dict,
                   count: int = 100) -> dict:
    """Analyze recent issues: response time, close rate, top labels."""
    
    url = f"{GITHUB_API}/repos/{owner_repo}/issues"
    PER_PAGE = 100
    params = {
        "state": "all",
        "sort": "created",
        "direction": "desc",
        "per_page": PER_PAGE
    }

    issues = fetch_issues(url, headers, params=params, max_items=count)
    all_issues = len(issues)

    response_times = []
    for issue in issues:
        creation_time = datetime.fromisoformat(issue["created_at"].rstrip("Z")).replace(tzinfo=timezone.utc)
        comment_time = first_comment_time(issue, headers)
        if comment_time:
            response_times.append(comment_time - creation_time)
    avg_response_time = sum(response_times, timedelta())/len(response_times) if response_times else None

    closed_issues = [issue for issue in issues if issue["state"] == "closed"]
    closed_count = len(closed_issues)
    close_rate = closed_count / all_issues * 100 if all_issues > 0 else 0

    all_labels = []
    for issue in issues:
        for label in issue["labels"]:
            all_labels.append(label["name"])
    label_counts = Counter(all_labels)
    top_labels = label_counts.most_common(5)

    return {
            "response_time": avg_response_time,
            "close_rate": close_rate,
            "top_labels": top_labels
            }

def analyze_pull_requests(owner_repo: str, headers: dict,
                          count: int = 50) -> dict:
    """Analyze recent pull requests: merge time, merge rate."""
    
    url = f"{GITHUB_API}/repos/{owner_repo}/pulls"
    PER_PAGE = count
    params = {
        "state": "all",
        "sort": "created",
        "direction": "desc",
        "per_page": PER_PAGE
    }

    r = requests.get(url, headers=headers, params=params)
    r.raise_for_status()
    pulls = r.json()
    all_pulls = len(pulls)

    merge_times = []
    for pull in pulls:
        if pull["merged_at"]:
            creation_time = datetime.fromisoformat(pull["created_at"].rstrip("Z")).replace(tzinfo=timezone.utc)
            merged_time = datetime.fromisoformat(pull["merged_at"].rstrip("Z")).replace(tzinfo=timezone.utc)
            merge_times.append(merged_time-creation_time)
    avg_merge_time = sum(merge_times, timedelta())/len(merge_times) if merge_times else None

    merged_count = len(merge_times)
    merged_rate = merged_count/all_pulls*100 if all_pulls>0 else 0

    rejected_pulls = [pull for pull in pulls if pull["state"]=="closed" and not pull["merged_at"]]
    rejected_count = len(rejected_pulls)
    rejected_rate = rejected_count/all_pulls*100 if all_pulls>0 else 0

    open_pulls = [pull for pull in pulls if pull["state"] == "open"]
    open_count = len(open_pulls)
    open_rate = open_count/all_pulls*100 if all_pulls>0 else 0

    return {
        "merge_time": avg_merge_time,
        "merged_rate": merged_rate,
        "rejected_rate": rejected_rate,
        "open_rate": open_rate
    }

def analyze_activity(owner_repo: str, headers: dict) -> dict:
    """Compare recent activity with a year ago."""
    
    # znajduje datę początku i końca ostatniego pełnego miesiąca
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=30)).isoformat()
    until = now.isoformat()

    url = f"{GITHUB_API}/repos/{owner_repo}/commits"
    params = {
        "since": since,
        "until": until
    }
    commits = fetch_paginated(url, headers, params=params)
    nr_commits = len(commits)

    # znajduje datę początku i końca tego samego miesiąca rok temu
    since = (now - timedelta(days=395)).isoformat()
    until = (now - timedelta(days=365)).isoformat()

    params = {
        "since": since,
        "until": until
    }
    commits_last_year = fetch_paginated(url, headers, params=params)
    nr_commits_last_year = len(commits_last_year)

    # wyciąga listę unikalnych kontrybutorów
    url = f"{GITHUB_API}/repos/{owner_repo}/contributors"
    contributors = fetch_paginated(url, headers)
    nr_contributors = len(contributors)

    return {
        "commits_last_month": nr_commits,
        "commits_year_ago": nr_commits_last_year,
        "contributors": nr_contributors
    }

def parse_time(time):
    seconds = time.total_seconds() if time else None
    days = seconds/86400 if seconds else None
    result = f"{days:.1f} dni" if days else "N/A"
    return result

def print_report(repo_info: dict, issues: dict, prs: dict,
                 activity: dict) -> None:
    """Print formatted report to console."""
    print(f"\n{'=' * 60}")
    print(f"PROFIL REPOZYTORIUM: {repo_info['full_name']}")
    print(f"{'=' * 60}")

    print(f"\n--- Podstawowe metryki ---")
    print(f"  Gwiazdki:                   {repo_info['stargazers_count']:,}")
    print(f"  Forki:                      {repo_info['forks_count']:,}")
    print(f"  Otwarte issues:             {repo_info['open_issues_count']:,}")
    print(f"  Obserwujący:                {repo_info['watchers_count']:,}")
    print(f"  Język:                      {repo_info.get('language', 'N/A')}")
    license_name = repo_info.get("license", {})
    print(f"  Licencja:                   {license_name.get('spdx_id', 'N/A') if license_name else 'N/A'}")

    print(f"\n--- Issues (ostatnie 100) ---")
    print(f"  Zamknięte:                  {issues['close_rate']:.0f}%")
    time = parse_time(issues['response_time'])
    print(f"  Średni czas odpowiedzi:     {time}")
    print(f"  Top etykiety:")
    if issues['top_labels']:
        for label, count in issues['top_labels']:
            print(f"    {label}: ({count})")
    else:
        print("    Brak etykiet")

    print(f"\n--- Pull Requests (ostatnie 50) ---")
    print(f"  Zmergowane:                 {prs['merged_rate']:.0f}%")
    print(f"  Odrzucone:                  {prs['rejected_rate']:.0f}%")
    print(f"  Otwarte:                    {prs['open_rate']:.0f}%")
    time = parse_time(prs['merge_time'])
    print(f"  Średni czas mergowania:     {time}")

    print(f"\n--- Aktywność ---")
    this_year = activity['commits_last_month']
    last_year = activity['commits_year_ago'] 
    print(f"  Commitów (ostatni miesiąc): {this_year:,}")
    print(f"  Commitów (rok temu):        {last_year:,}")
    if this_year==last_year:
        print(f"  Aktywność:                  bez zmian")
    elif this_year>last_year:
        trend = (this_year-last_year)/last_year*100 if last_year>0 else 100
        print(f"  Aktywność:                  wzrost o {trend:.0f}%")
    else:
        trend = (last_year-this_year)/last_year*100 if last_year>0 else 100
        print(f"  Aktywność:                  spadek o {trend:.0f}%")
    print(f"  Unikalnych kontrybutorów:   {activity['contributors']:,}")

def print_row(name, val1, val2):
    print(f"{name:<30} {val1:<15} {val2:<15}")

def print_comparison(owner_repo1: str, owner_repo2: str,
                     repo_info1: dict, repo_info2: dict,
                     issues1: dict, issues2: dict,
                     prs1: dict, prs2: dict, 
                     activity1: dict, activity2: dict) -> None:
    """Print side-by-side comparison of two repositories."""
    
    repo1 = owner_repo1.split("/")[1]
    repo2 = owner_repo2.split("/")[1]

    score1 = 0
    score2 = 0
    reasons1 = []
    reasons2 = []

    print(f"PORÓWNANIE: {owner_repo1} vs {owner_repo2}")
    print('=' * 60)
    print(f"{'Metryka':<30} {repo1:<15} {repo2:<15}")
    print('=' * 60)

    stars1 = repo_info1['stargazers_count']
    stars2 = repo_info2['stargazers_count']
    print_row("Gwiazdki", f"{stars1:,}", f"{stars2:,}")
    if stars1>stars2:
        score1 += 1
        reasons1.append("ma więcej gwiazdek")
    elif stars2>stars1:
        score2 += 1
        reasons2.append("ma więcej gwiazdek")    

    print_row("Forki", f"{repo_info1['forks_count']:,}", f"{repo_info2['forks_count']:,}")
    print_row("Otwarte issues", f"{repo_info1['open_issues_count']:,}", f"{repo_info2['open_issues_count']:,}")
    closed1 = issues1['close_rate']
    closed2 = issues2['close_rate']
    print_row("% zamkniętych issues", f"{closed1:.0f}%", f"{closed2:.0f}%")
    if closed1>closed2:
        score1 += 1
        reasons1.append("zamyka większy % issues")
    elif closed2>closed1:
        score2 += 1
        reasons2.append("zamyka większy % issues")

    time1 = issues1['response_time']
    time2 = issues2['response_time']
    if time1 and time2:
        if time1<time2:
            score1 += 1
            reasons1.append("szybciej odpowiada na issues")
        elif time2<time1:
            score2 += 1
            reasons2.append("szybciej odpowiada na issues") 
    time1 = parse_time(time1)
    time2 = parse_time(time2)
    print_row("Śr. czas odpowiedzi", time1, time2)
     
    merged1 = prs1['merged_rate']
    merged2 = prs2['merged_rate'] 
    print_row("% zmergowanych PR", f"{merged1:.0f}%", f"{merged2:.0f}%")
    if merged1>merged2:
        score1 += 1
        reasons1.append("ma większy % zmergowanych PR")
    elif merged2>merged1:
        score2 += 1
        reasons2.append("ma większy % zmergowanych PR")
   
    time1 = prs1['merge_time']
    time2 = prs2['merge_time']
    if time1 and time2:
        if time1<time2:
            score1 += 1
            reasons1.append("szybciej merguje PR")
        elif time2<time1:
            score2 += 1
            reasons2.append("szybciej merguje PR")
    time1 = parse_time(time1)
    time2 = parse_time(time2)
    print_row("Śr. czas merge", time1, time2)

    activ1 = activity1['commits_last_month']
    activ2 = activity2['commits_last_month']
    print_row("Commitów (ost. miesiąc)", activ1, activ2)
    if activ1>activ2:
        score1 += 1
        reasons1.append("ma więcej commitów w ostatnim miesiącu")
    elif activ2>activ1:
        score2 += 1
        reasons2.append("ma więcej commitów w ostatnim miesiącu")

    if score1>score2:
        print(f"Verdict: {repo1} wygląda na zdrowsze repozytorium, ponieważ:")
        for reason in reasons1:
            print(f"  > {reason}")
    elif score2>score1:
        print(f"Verdict: {repo2} wygląda na zdrowsze repozytorium, ponieważ:")
        for reason in reasons2:
            print(f"  > {reason}")
    else:
        print("\nVerdict: oba repozytoria wyglądają podobnie zdrowo.")

def main():
    if len(sys.argv) < 2:
        print("Użycie: python github_profiler.py <owner/repo>")
        print("Przykład: python github_profiler.py psf/requests")
        sys.exit(1)

    headers = get_headers()

    # wersja do pełnej analizy jednego repozytorium
    if len(sys.argv)==2:
        owner_repo = sys.argv[1]
        print(f"Profiluję {owner_repo}...")

        repo_info = get_repo_info(owner_repo, headers)
        issues = analyze_issues(owner_repo, headers)
        prs = analyze_pull_requests(owner_repo, headers)
        activity = analyze_activity(owner_repo, headers)

        print_report(repo_info, issues, prs, activity)

    # wersja do porównania dwóch repozytoriów
    elif len(sys.argv)==3:
        owner_repo_1 = sys.argv[1]
        owner_repo_2 = sys.argv[2]

        repo_info_1 = get_repo_info(owner_repo_1, headers)
        issues_1 = analyze_issues(owner_repo_1, headers)
        prs_1 = analyze_pull_requests(owner_repo_1, headers)
        activity_1 = analyze_activity(owner_repo_1, headers)

        repo_info_2 = get_repo_info(owner_repo_2, headers)
        issues_2 = analyze_issues(owner_repo_2, headers)
        prs_2 = analyze_pull_requests(owner_repo_2, headers)
        activity_2 = analyze_activity(owner_repo_2, headers)

        print_comparison(owner_repo_1, owner_repo_2,
                         repo_info_1, repo_info_2,
                         issues_1, issues_2,
                         prs_1, prs_2,  
                         activity_1, activity_2)

if __name__ == "__main__":
    main()