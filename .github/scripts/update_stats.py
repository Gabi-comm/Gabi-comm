import os
import requests

# Grab the token and username automatically from GitHub Actions
TOKEN = os.environ.get('GH_TOKEN')
REPO = os.environ.get('GITHUB_REPOSITORY', '/')
USERNAME = REPO.split('/')[0]

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

try:
    req = requests.post('https://api.github.com/graphql', json={'query': query}, headers=headers)
    res_data = req.json()
    data = res_data['data']['user']
    
    # Calculate totals
    stars = sum(node['stargazers']['totalCount'] for node in data['repositories']['nodes'])
    commits = data['contributionsCollection']['totalCommitContributions']
    prs = data['pullRequests']['totalCount']
    issues = data['issues']['totalCount']
    contribs = data['repositoriesContributedTo']['totalCount']
except Exception as e:
    print(f"Error fetching data from GitHub API: {e}")
    exit(1)

# Format to look like the clean monospace WakaTime UI
text_ui = f"""```text
🎯 GitHub Statistics:
⭐ Total Stars Earned:       {stars}
🔄 Total Commits (1 yr):     {commits}
🔀 Total PRs:                {prs}
❗ Total Issues:             {issues}
🎒 Contributed to (1 yr):    {contribs}
```"""

START_TAG = ""
END_TAG = ""

if os.path.exists('README.md'):
    with open('README.md', 'r', encoding='utf-8') as f:
        readme = f.read()
        
    if START_TAG in readme and END_TAG in readme:
        # Isolate everything before and after the blocks safely
        before_content = readme.split(START_TAG)[0]
        after_content = readme.split(END_TAG)[1]
        
        # Re-assemble the README with the fresh UI stats in the middle
        new_readme = f"{before_content}{START_TAG}\n{text_ui}\n{END_TAG}{after_content}"
        
        with open('README.md', 'w', encoding='utf-8') as f:
            f.write(new_readme)
        print("README updated successfully without touching other content!")
    else:
        print("Error: Could not find matching START or END tags in your README.md")
else:
    print("Error: README.md file not found.")
