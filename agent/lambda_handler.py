"""
AWS Lambda Handler — Democratic Stress Index Agent
===================================================
Entry point for Lambda. Secrets are fetched from AWS Secrets Manager
by secrets.py — NOT from environment variables.

Lambda environment variables to set (non-sensitive, safe in config):
  GITHUB_REPO       — e.g. "dasumner/democratic-stress-dashboard"
  GITHUB_BRANCH     — default: "main"
  DATA_FILE_PATH    — default: "data/metrics.json"
  DSI_SECRET_NAME   — Secrets Manager secret name, default: "dsi/secrets"
  AWS_REGION        — auto-set by Lambda, but can override

Lambda execution role must have the policy in infra/iam_policy.json attached.

Recommended Lambda settings:
  Runtime:  Python 3.12
  Memory:   256 MB
  Timeout:  120 seconds
  Trigger:  EventBridge Scheduler (e.g. rate(6 hours))
"""

import json
import logging
import traceback
from agent import main as run_agent

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def handler(event, context):
    """Lambda entry point."""
    log.info("Lambda cold/warm start — handler invoked")

    try:
        result = run_agent()
        body = {
            "status": "success",
            "run_count": result["meta"]["run_count"],
            "composite_stress": result["current"]["composite_stress"],
            "last_updated": result["meta"]["last_updated"],
        }
        log.info(f"Run complete: {body}")
        return {"statusCode": 200, "body": json.dumps(body)}

    except Exception as e:
        log.error(f"Agent run failed: {e}")
        log.error(traceback.format_exc())
        return {
            "statusCode": 500,
            "body": json.dumps({"status": "error", "error": str(e)})
        }
