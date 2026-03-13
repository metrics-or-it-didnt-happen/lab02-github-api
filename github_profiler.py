import os
import requests
import sys
from datetime import datetime, timedelta
from collections import Counter

# Klucz do przeżycia: Token z zmiennej środowiskowej
TOKEN = os.getenv('GITHUB_TOKEN')
HEADERS = {'Authorization': f'token {TOKEN}'} if TOKEN else {}
BASE_URL = "https://api.github.com/repos"

def get_json(url, params=None):
    response = requests.get(url, headers=HEADERS, params=params)
    if response.status_code != 200:
        print(f"Błąd API: {response.status_code} dla {url}")
        return None
    return response.json()

def calculate_avg_time(time_diffs):
    if not time_diffs: return "N/A"
    avg_seconds = sum(time_diffs) / len(time_diffs)
    hours = avg_seconds / 3600
    return f"{hours:.1f} h"

def profile_repo(repo_path):
    print(f"--- Generuję profil dla: {repo_path} ---")
    
    # 1. Podstawowe metryki
    repo_data = get_json(f"{BASE_URL}/{repo_path}")
    if not repo_data: return

    print(f"Stars: {repo_data['stargazers_count']}")
    print(f"Forks: {repo_data['forks_count']}")
    print(f"Open Issues: {repo_data['open_issues_count']}")
    print(f"Language: {repo_data['language']}")
    print(f"License: {repo_data['license']['name'] if repo_data['license'] else 'None'}")

    # 2. Analiza Issues (ostatnie 100)
    issues = get_json(f"{BASE_URL}/{repo_path}/issues", {"state": "all", "per_page": 100})
    # GitHub API miesza issues z PRami, musimy odfiltrować
    real_issues = [i for i in issues if 'pull_request' not in i]
    
    closed_count = sum(1 for i in real_issues if i['state'] == 'closed')
    open_count = len(real_issues) - closed_count
    
    # Czas do pierwszej odpowiedzi
    response_times = []
    labels_counter = Counter()

    for i in real_issues:
        for label in i['labels']:
            labels_counter[label['name']] += 1
        
        if i['comments'] > 0:
            comments = get_json(i['comments_url'])
            if comments:
                created_at = datetime.strptime(i['created_at'], "%Y-%m-%dT%H:%M:%SZ")
                first_comm = datetime.strptime(comments[0]['created_at'], "%Y-%m-%dT%H:%M:%SZ")
                response_times.append((first_comm - created_at).total_seconds())

    print(f"\n[Issues Analysis]")
    print(f"Closed vs Open: {closed_count}/{open_count} ({(closed_count/len(real_issues)*100):.1f}% closed)")
    print(f"Avg time to first response: {calculate_avg_time(response_times)}")
    print(f"Top Labels: {', '.join([l[0] for l in labels_counter.most_common(5)])}")

    # 3. Analiza PR (ostatnie 50)
    prs = get_json(f"{BASE_URL}/{repo_path}/pulls", {"state": "all", "per_page": 50})
    merge_times = []
    merged = rejected = opened = 0

    for p in prs:
        if p['state'] == 'open':
            opened += 1
        elif p.get('merged_at'):
            merged += 1
            start = datetime.strptime(p['created_at'], "%Y-%m-%dT%H:%M:%SZ")
            end = datetime.strptime(p['merged_at'], "%Y-%m-%dT%H:%M:%SZ")
            merge_times.append((end - start).total_seconds())
        else:
            rejected += 1

    print(f"\n[Pull Requests]")
    print(f"Merged: {merged}, Rejected: {rejected}, Open: {opened}")
    print(f"Avg time to merge: {calculate_avg_time(merge_times)}")

    # 4. Aktywność
    now = datetime.utcnow()
    last_month_start = (now - timedelta(days=30)).isoformat()
    year_ago_start = (now - timedelta(days=395)).isoformat() # ok. rok temu
    year_ago_end = (now - timedelta(days=365)).isoformat()

    commits_now = get_json(f"{BASE_URL}/{repo_path}/commits", {"since": last_month_start})
    commits_year = get_json(f"{BASE_URL}/{repo_path}/commits", {"since": year_ago_start, "until": year_ago_end})

    print(f"\n[Activity]")
    print(f"Commits (last 30 days): {len(commits_now) if commits_now else 0}")
    print(f"Commits (same month year ago): {len(commits_year) if commits_year else 0}")

    # 5. Unikatowi kontrybutorzy
    # API GitHub zwraca max 30 na stronę, musimy sprawdzić nagłówek 'link' dla ostatniej strony
    contributors_resp = requests.get(f"{BASE_URL}/{repo_path}/contributors", headers=HEADERS, params={"per_page": 1, "anon": "true"})
    # Trick studencki: nagłówek 'Link' ma info o ostatniej stronie (czyli liczbie osób)
    if 'Link' in contributors_resp.headers:
        last_url = contributors_resp.headers['Link'].split(',')[1]
        count = last_url.split('page=')[1].split('>')[0]
        print(f"Total contributors: ~{count}")
    else:
        print(f"Total contributors: {len(get_json(f'{BASE_URL}/{repo_path}/contributors'))}")

if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "psf/requests"
    profile_repo(repo)