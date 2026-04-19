"""
Democratic Stress Index — Monitoring Agent
==========================================
Runs locally or as an AWS Lambda function.
Calls Claude with web search, updates data/metrics.json, pushes to GitHub.

Secrets (ANTHROPIC_API_KEY, GITHUB_TOKEN) are fetched from:
  - AWS Secrets Manager when running in Lambda
  - Environment variables when running locally

Non-sensitive config via environment variables (safe to set in Lambda):
    GITHUB_REPO         — e.g. "dasumner/democratic-stress-dashboard"
    GITHUB_BRANCH       — default: "main"
    DATA_FILE_PATH      — default: "data/metrics.json"
    DSI_SECRET_NAME     — Secrets Manager secret name, default: "dsi/secrets"
    AWS_REGION          — default: "us-east-1"

Local usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    export GITHUB_TOKEN=ghp_...
    export GITHUB_REPO=dasumner/democratic-stress-dashboard
    python agent.py
"""

import os
import json
import base64
import logging
import datetime
from typing import Optional
import anthropic
import urllib.request
import urllib.error

import secrets as sec   # our secrets.py module

# ─── LOGGING ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ─── NON-SENSITIVE CONFIG (safe as Lambda env vars) ───────────────────────────
GITHUB_REPO    = os.environ["GITHUB_REPO"]
GITHUB_BRANCH  = os.environ.get("GITHUB_BRANCH", "main")
DATA_FILE_PATH = os.environ.get("DATA_FILE_PATH", "data/metrics.json")

MONITOR_SOURCES = [
    {
        "id": "institutional",
        "label": "Institutional Integrity",
        "metric_key": "institutional",
        "description": "Congressional oversight actions, court order compliance, executive overreach",
        "query": "US Congress executive oversight actions court order compliance 2025 2026",
    },
    {
        "id": "economic",
        "label": "Economic Health",
        "metric_key": "economic",
        "description": "Median household wages, inflation, unemployment, middle class conditions",
        "query": "US median household income inflation unemployment economic conditions 2025 2026",
    },
    {
        "id": "civil_rights",
        "label": "Civil Rights Index",
        "metric_key": "civil_rights",
        "description": "DEI policy rollbacks, voting access, minority protections, gender rights",
        "query": "US civil rights rollbacks DEI voting rights minority protections 2025 2026",
    },
    {
        "id": "distraction",
        "label": "Distraction Index",
        "metric_key": "distraction",
        "description": "Culture war legislation, wedge issue media volume, scapegoating events",
        "query": "US culture war legislation wedge issues political distraction media 2025 2026",
    },
    {
        "id": "gini",
        "label": "Wealth Divergence",
        "metric_key": "gini",
        "description": "Gini coefficient, top 1% wealth share, median vs elite divergence",
        "query": "US wealth inequality gini coefficient top 1 percent 2025 2026",
    },
]

AGENT_SYSTEM_PROMPT = """You are a political and economic data analyst.
Your job is to search the web for current information and return a structured JSON assessment.
Always respond ONLY with valid JSON — no markdown, no backticks, no preamble or postamble."""

def build_agent_prompt(sources: list) -> str:
    source_list = "\n".join(
        f'- {s["label"]} (key: "{s["metric_key"]}"): {s["description"]}\n  Search hint: {s["query"]}'
        for s in sources
    )
    return f"""Search the web for current information on these US democratic health indicators.
Return a JSON object with updated scores.

METRICS (score 0–100 each, except gini):
{source_list}

SCORING GUIDE:
- institutional: 100 = checks/balances fully functioning, 0 = complete breakdown
- economic: 100 = strong broad-based prosperity, 0 = severe economic distress
- civil_rights: 100 = full protections enforced, 0 = widespread rollbacks
- distraction: 100 = maximum cultural wedge/scapegoating activity, 0 = none (HIGHER = WORSE)
- gini: return the ACTUAL Gini coefficient value (e.g. 49.5), NOT a 0–100 score

ALSO RETURN:
- summary: 2–3 sentence plain-English assessment of current conditions
- alerts: array of up to 3 notable recent events, each:
    {{"title": "...", "severity": "high"|"medium"|"low", "date": "YYYY-MM-DD"}}
- sources_consulted: array of up to 5 publication/outlet names used
- timestamp: current UTC datetime as ISO 8601 string

REQUIRED JSON FORMAT (respond with ONLY this, no other text):
{{
  "institutional": <int 0-100>,
  "economic": <int 0-100>,
  "civil_rights": <int 0-100>,
  "distraction": <int 0-100>,
  "gini": <float>,
  "summary": "<string>",
  "alerts": [{{"title": "...", "severity": "...", "date": "..."}}],
  "sources_consulted": ["..."],
  "timestamp": "<ISO datetime>"
}}"""


# ─── CLAUDE AGENT ─────────────────────────────────────────────────────────────
def run_claude_agent() -> dict:
    """Call Claude with web search and return parsed metrics dict."""
    log.info("Initializing Anthropic client...")
    client = anthropic.Anthropic(api_key=sec.get("ANTHROPIC_API_KEY"))

    log.info("Sending request to Claude with web_search tool...")
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1500,
        system=AGENT_SYSTEM_PROMPT,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": build_agent_prompt(MONITOR_SOURCES)}],
    )

    # Count searches performed
    search_count = sum(1 for b in response.content if b.type == "tool_use")
    log.info(f"Agent performed {search_count} web search(es)")

    # Extract text blocks
    text = "".join(b.text for b in response.content if b.type == "text")
    log.info("Raw response received, parsing JSON...")

    # Strip any accidental markdown fences
    clean = text.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    clean = clean.strip()

    # Find JSON object
    start = clean.find("{")
    end   = clean.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found in response: {clean[:200]}")

    parsed = json.loads(clean[start:end])
    log.info("JSON parsed successfully")
    return parsed


# ─── GITHUB ───────────────────────────────────────────────────────────────────
def github_get_file(path: str) -> tuple[Optional[str], Optional[str]]:
    """Fetch file content and SHA from GitHub. Returns (content_str, sha)."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}?ref={GITHUB_BRANCH}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {sec.get('GITHUB_TOKEN')}",
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            content = base64.b64decode(data["content"]).decode("utf-8")
            return content, data["sha"]
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        raise


def github_push_file(path: str, content: str, sha: Optional[str], message: str):
    """Create or update a file in the GitHub repo."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="PUT", headers={
        "Authorization": f"token {sec.get('GITHUB_TOKEN')}",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
        log.info(f"GitHub push successful: {result['commit']['sha'][:8]}")


# ─── MERGE METRICS ────────────────────────────────────────────────────────────
def merge_metrics(existing: dict, agent_result: dict) -> dict:
    """Merge agent results into existing metrics.json structure."""
    now = datetime.datetime.utcnow()
    date_label = now.strftime("%Y-%m")  # e.g. "2026-04"

    # Build new current scores
    current = {
        "institutional": int(agent_result.get("institutional", existing["current"]["institutional"])),
        "economic":      int(agent_result.get("economic",      existing["current"]["economic"])),
        "civil_rights":  int(agent_result.get("civil_rights",  existing["current"]["civil_rights"])),
        "distraction":   int(agent_result.get("distraction",   existing["current"]["distraction"])),
        "gini":          float(agent_result.get("gini",        existing["current"]["gini"])),
    }
    # Composite stress: average of inverted non-distraction metrics + distraction
    current["composite_stress"] = round(
        (100 - current["institutional"] +
         100 - current["economic"] +
         100 - current["civil_rights"] +
         current["distraction"]) / 4
    )

    # Build history entry
    history_entry = {
        "date": date_label,
        **{k: v for k, v in current.items()},
    }

    # Update or append history for this month
    history = existing.get("history", [])
    history = [h for h in history if h["date"] != date_label]
    history.append(history_entry)
    history = sorted(history, key=lambda h: h["date"])[-24:]  # keep last 24 months

    # Merge alerts
    new_alerts = agent_result.get("alerts", [])
    existing_alerts = existing.get("alerts", [])
    merged_alerts = (new_alerts + existing_alerts)[:20]

    return {
        "meta": {
            "last_updated": agent_result.get("timestamp", now.isoformat() + "Z"),
            "agent_version": existing.get("meta", {}).get("agent_version", "1.0.0"),
            "run_count": existing.get("meta", {}).get("run_count", 0) + 1,
        },
        "current": current,
        "summary": agent_result.get("summary", existing.get("summary", "")),
        "alerts": merged_alerts,
        "sources_consulted": agent_result.get("sources_consulted", []),
        "history": history,
    }


# ─── MAIN ─────────────────────────────────────────────────────────────────────
def main():
    log.info("=" * 60)
    log.info("Democratic Stress Index — Agent Run")
    log.info("=" * 60)

    # 1. Fetch current metrics.json from GitHub
    log.info(f"Fetching {DATA_FILE_PATH} from {GITHUB_REPO}...")
    existing_raw, sha = github_get_file(DATA_FILE_PATH)
    existing = json.loads(existing_raw) if existing_raw else {
        "meta": {"last_updated": "", "agent_version": "1.0.0", "run_count": 0},
        "current": {"institutional": 50, "economic": 50, "civil_rights": 50, "distraction": 50, "gini": 48.0, "composite_stress": 50},
        "summary": "",
        "alerts": [],
        "sources_consulted": [],
        "history": [],
    }
    log.info(f"Loaded existing data (run #{existing['meta'].get('run_count', 0)})")

    # 2. Run Claude agent
    log.info("Running Claude agent with web search...")
    agent_result = run_claude_agent()
    log.info(f"Agent returned: {list(agent_result.keys())}")

    # 3. Merge and build updated JSON
    updated = merge_metrics(existing, agent_result)
    updated_str = json.dumps(updated, indent=2)
    log.info(f"Composite stress score: {updated['current']['composite_stress']}")

    # 4. Push to GitHub
    run_num = updated["meta"]["run_count"]
    commit_msg = f"chore: agent run #{run_num} — stress={updated['current']['composite_stress']} [{datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC]"
    log.info(f"Pushing to GitHub: {commit_msg}")
    github_push_file(DATA_FILE_PATH, updated_str, sha, commit_msg)

    log.info("Agent run complete.")
    return updated


if __name__ == "__main__":
    main()
