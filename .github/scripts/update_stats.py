import os
import requests
import re

# Grab the token and username automatically from GitHub Actions
TOKEN = os.environ.get('GH_TOKEN')
USERNAME = os.environ.get('GITHUB_REPOSITORY').split('/')[0]

headers = {"Authorization": f"Bearer {TOKEN}"}

# Query GitHub's GraphQL API for your stats
query = """
{
  user(login: "%s") {
    repositories(first: 100, ownerAffiliations: OWNER) {
      nodes {
        stargazers { totalCount }
      }
    }
    pullRequests(first: 1) { totalCount }
    issues(first: 1) { totalCount }
    contributionsCollection {
      totalCommitContributions
    }
    repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]) {
      totalCount
    }
  }
}
""" % USERNAME

# Fetch the data
req = requests.post('https://api.github.com/graphql', json={'query': query}, headers=headers)
data = req.json()['data']['user']

# Calculate totals
stars = sum(node['stargazers']['totalCount'] for node in data['repositories']['nodes'])
commits = data['contributionsCollection']['totalCommitContributions']
prs = data['pullRequests']['totalCount']
issues = data['issues']['totalCount']
contribs = data['repositoriesContributedTo']['totalCount']

# Format it to look like the clean WakaTime text UI
text_ui = f"""```text
🎯 GitHub Statistics:
⭐ Total Stars Earned:       {stars}
🔄 Total Commits (1 yr):     {commits}
🔀 Total PRs:                {prs}
❗ Total Issues:             {issues}
🎒 Contributed to (1 yr):    {contribs}
```"""

# Inject the text into the README
with open('README.md', 'r', encoding='utf-8') as f:
    readme = f.read()

readme = re.sub(
    r'(?<=).*?(?=)',
    f'\n{text_ui}\n',
    readme,
    flags=re.DOTALL
)

with open('README.md', 'w', encoding='utf-8') as f:
    f.write(readme)
