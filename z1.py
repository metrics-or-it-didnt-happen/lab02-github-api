import os
import requests

token = os.environ["TOKEN"]
headers = {"Authorization": f"token {token}"}

response = requests.get(
    "https://api.github.com/repos/psf/requests",
    headers=headers,
)
repo = response.json()

print(f"Nazwa: {repo['full_name']}")
print(f"Gwiazdki: {repo['stargazers_count']}")
print(f"Forki: {repo['forks_count']}")
print(f"Otwarte issues: {repo['open_issues_count']}")
print(f"Język: {repo['language']}")

r = requests.get("https://api.github.com/rate_limit", headers=headers)
limits = r.json()["rate"]
print(f"Limit: {limits['limit']}/h")
print(f"Pozostało: {limits['remaining']}")
print(f"Reset: {limits['reset']}")