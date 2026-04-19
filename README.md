# Democratic Stress Index — Static Site + Monitoring Agent

A static dashboard hosted on GitHub Pages, updated automatically by an AI agent
that searches the web and scores key democratic health indicators.

## Architecture

```
GitHub Repo (static site)
├── index.html              # Dashboard — reads data/metrics.json on load
├── assets/style.css
├── assets/app.js
├── data/metrics.json       ← agent writes here on each run
└── agent/
    ├── agent.py            # Core logic
    ├── secrets.py          # AWS Secrets Manager client (with local fallback)
    ├── lambda_handler.py   # Lambda entry point
    ├── requirements.txt
    └── infra/
        ├── template.yaml       # SAM/CloudFormation deployment
        ├── iam_policy.json     # Least-privilege IAM policy reference
        └── create_secrets.sh   # One-time secrets setup script

Secret storage:
  Sensitive  → AWS Secrets Manager (ANTHROPIC_API_KEY, GITHUB_TOKEN)
  Non-secret → Lambda env vars    (GITHUB_REPO, GITHUB_BRANCH, etc.)
```

### Data flow
```
EventBridge Scheduler
  → Lambda (dsi-monitoring-agent)
    → secrets.py fetches keys from Secrets Manager (cached per cold start)
    → agent.py calls Claude with web_search tool
    → Claude scores metrics, returns JSON
    → agent.py pushes updated data/metrics.json to GitHub
      → GitHub Pages serves the updated static site
```

---

## Setup

### 1. Enable GitHub Pages

1. Fork or push this repo to GitHub
2. **Settings → Pages → Deploy from branch → main → / (root)**
3. Dashboard live at `https://dasumner.github.io/democratic-stress-dashboard/`

---

### 2. Store secrets in AWS Secrets Manager

```bash
cd agent/infra
chmod +x create_secrets.sh
./create_secrets.sh
```

This creates a secret named `dsi/secrets` containing:
```json
{
  "ANTHROPIC_API_KEY": "sk-ant-...",
  "GITHUB_TOKEN":      "ghp_..."
}
```

Your GitHub token needs **Contents: Read and Write** on the repo only.
Create a fine-grained PAT at github.com/settings/tokens.

---

### 3. Deploy Lambda with SAM

```bash
pip install aws-sam-cli   # if not installed

cd agent/infra
sam build
sam deploy --guided

# Parameters prompted:
#   GithubRepo         → dasumner/democratic-stress-dashboard
#   GithubBranch       → main
#   SecretName         → dsi/secrets
#   ScheduleExpression → rate(6 hours)
```

SAM creates the Lambda, execution role, EventBridge scheduler, and log group.

Subsequent deploys: `sam build && sam deploy`

---

### 4. Test manually

```bash
aws lambda invoke \
  --function-name dsi-monitoring-agent \
  --log-type Tail \
  --output json response.json && cat response.json

# Live logs
aws logs tail /aws/lambda/dsi-monitoring-agent --follow
```

---

### Local development

```bash
cd agent
pip install -r requirements.txt

export ANTHROPIC_API_KEY=sk-ant-...
export GITHUB_TOKEN=ghp_...
export GITHUB_REPO=dasumner/democratic-stress-dashboard

python agent.py
```

`secrets.py` detects it is not in Lambda and falls back to env vars automatically.

---

## Security model

| What | Where | Accessible to |
|------|-------|---------------|
| `ANTHROPIC_API_KEY` | Secrets Manager | Lambda role only (ARN-scoped) |
| `GITHUB_TOKEN` | Secrets Manager | Lambda role only (ARN-scoped) |
| `GITHUB_REPO` | Lambda env vars | Anyone with Lambda read access |
| `GITHUB_BRANCH` | Lambda env vars | Anyone with Lambda read access |

- IAM policy is scoped to the exact secret ARN — not `*`
- Secrets never appear in Lambda config, logs, or environment
- Secrets cached in memory per cold start — one Secrets Manager call per container lifetime
- Rotation: update the secret in Secrets Manager; next cold start picks it up automatically

---

## Metrics tracked

| Metric | Key | Range | Note |
|--------|-----|-------|------|
| Institutional Integrity | `institutional` | 0–100 | Higher = healthier |
| Economic Health | `economic` | 0–100 | Higher = healthier |
| Civil Rights Index | `civil_rights` | 0–100 | Higher = more protected |
| Distraction Index | `distraction` | 0–100 | Higher = worse |
| Wealth Divergence | `gini` | actual Gini | e.g. 49.5 |

---

## License

MIT
