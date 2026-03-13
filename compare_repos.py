import os
import requests
import sys
from datetime import datetime, timedelta, timezone
from collections import Counter

# Konfiguracja API
TOKEN = os.getenv('GITHUB_TOKEN')
HEADERS = {'Authorization': f'token {TOKEN}'} if TOKEN else {}
BASE_URL = "https://api.github.com/repos"

def get_json(url, params=None):
    """Pobiera dane z API z obsługą paginacji jeśli params['per_page'] jest ustawione."""
    all_data = []
    page = 1
    
    # Jeśli zapytanie nie dotyczy listy (np. info o repo), pobierz raz
    if "per_page" not in (params or {}):
        response = requests.get(url, headers=HEADERS, params=params)
        return response.json() if response.status_code == 200 else None

    # Paginacja dla list (np. issues, commits)
    max_items = params.get('max_items', 100)
    while len(all_data) < max_items:
        params['page'] = page
        response = requests.get(url, headers=HEADERS, params=params)
        if response.status_code != 200: break
        
        data = response.json()
        if not data: break
        
        all_data.extend(data)
        if len(data) < params['per_page']: break
        page += 1
        
    return all_data[:max_items]

def get_repo_stats(repo_path):
    """Zbiera wszystkie wymagane metryki dla jednego repozytorium."""
    stats = {}
    
    # Podstawowe info
    repo_data = get_json(f"{BASE_URL}/{repo_path}")
    if not repo_data: return None
    
    stats['stars'] = repo_data['stargazers_count']
    stats['forks'] = repo_data['forks_count']
    stats['open_issues_count'] = repo_data['open_issues_count']

    # Analiza Issues (ostatnie 100)
    # Filtrujemy PRy, bo API GitHub zwraca je razem w endpoincie /issues
    issues_raw = get_json(f"{BASE_URL}/{repo_path}/issues", {"state": "all", "per_page": 100, "max_items": 100})
    real_issues = [i for i in issues_raw if 'pull_request' not in i]
    
    closed_issues = [i for i in real_issues if i['state'] == 'closed']
    stats['pct_closed_issues'] = (len(closed_issues) / len(real_issues) * 100) if real_issues else 0
    
    # Średni czas odpowiedzi (dni)
    resp_days = []
    for i in real_issues:
        if i['comments'] > 0:
            comments = get_json(i['comments_url'], {"per_page": 1}) # Bierzemy tylko pierwszy komentarz
            if comments:
                created = datetime.strptime(i['created_at'], "%Y-%m-%dT%H:%M:%SZ")
                first = datetime.strptime(comments[0]['created_at'], "%Y-%m-%dT%H:%M:%SZ")
                resp_days.append((first - created).total_seconds() / 86400)
    
    stats['avg_resp_time'] = sum(resp_days) / len(resp_days) if resp_days else 0

    # Analiza PR (ostatnie 50)
    prs = get_json(f"{BASE_URL}/{repo_path}/pulls", {"state": "all", "per_page": 50, "max_items": 50})
    merged_prs = [p for p in prs if p.get('merged_at')]
    stats['pct_merged_pr'] = (len(merged_prs) / len(prs) * 100) if prs else 0
    
    m_days = []
    for p in merged_prs:
        start = datetime.strptime(p['created_at'], "%Y-%m-%dT%H:%M:%SZ")
        end = datetime.strptime(p['merged_at'], "%Y-%m-%dT%H:%M:%SZ")
        m_days.append((end - start).total_seconds() / 86400)
    
    stats['avg_merge_time'] = sum(m_days) / len(m_days) if m_days else 0

    # Aktywność (ostatni miesiąc)
    last_month = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    commits = get_json(f"{BASE_URL}/{repo_path}/commits", {"since": last_month, "per_page": 100, "max_items": 100})
    stats['commits_last_month'] = len(commits) if commits else 0
    
    return stats

def compare(repo1_path, repo2_path):
    s1 = get_repo_stats(repo1_path)
    s2 = get_repo_stats(repo2_path)
    
    if not s1 or not s2:
        print("Nie udało się pobrać danych dla jednego z repozytoriów.")
        return

    print(f"\nPORÓWNANIE: {repo1_path} vs {repo2_path}")
    print("=" * 65)
    header = f"{'Metryka':<25}{repo1_path:>20}{repo2_path:>20}"
    print(header)
    print("-" * 65)
    
    rows = [
        ("Gwiazdki", f"{s1['stars']:,}", f"{s2['stars']:,}"),
        ("Forki", f"{s1['forks']:,}", f"{s2['forks']:,}"),
        ("Otwarte issues", s1['open_issues_count'], s2['open_issues_count']),
        ("% zamkniętych issues", f"{s1['pct_closed_issues']:.1f}%", f"{s2['pct_closed_issues']:.1f}%"),
        ("Śr. czas odpowiedzi", f"{s1['avg_resp_time']:.1f} dni", f"{s2['avg_resp_time']:.1f} dni"),
        ("% zmergowanych PR", f"{s1['pct_merged_pr']:.1f}%", f"{s2['pct_merged_pr']:.1f}%"),
        ("Śr. czas merge", f"{s1['avg_merge_time']:.1f} dni", f"{s2['avg_merge_time']:.1f} dni"),
        ("Commitów (ost. miesiąc)", s1['commits_last_month'], s2['commits_last_month']),
    ]
    
    for label, v1, v2 in rows:
        print(f"{label:<25}{str(v1):>20}{str(v2):>20}")

    # Logika werdyktu
    v1_score = 0
    if s1['avg_resp_time'] < s2['avg_resp_time']: v1_score += 1
    if s1['commits_last_month'] > s2['commits_last_month']: v1_score += 1
    if s1['pct_closed_issues'] > s2['pct_closed_issues']: v1_score += 1
    
    print("\nVerdict: ", end="")
    if v1_score >= 2:
        print(f"{repo1_path} wygląda zdrowiej (szybsza reakcja i wyższa aktywność).")
    else:
        print(f"{repo2_path} wygląda zdrowiej (lepsze wskaźniki utrzymania i responsywności).")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Użycie: python compare_repos.py owner/repo1 owner/repo2")
    else:
        compare(sys.argv[1], sys.argv[2])