"""
secrets.py — AWS Secrets Manager client with in-memory caching
==============================================================
Fetches secrets once per Lambda cold start, then serves from cache.
Falls back to environment variables for local development.

Secret structure in AWS Secrets Manager (store as JSON):
  Secret name: dsi/secrets  (or set DSI_SECRET_NAME env var)
  Secret value:
    {
      "ANTHROPIC_API_KEY": "sk-ant-...",
      "GITHUB_TOKEN":      "ghp_..."
    }
"""

import os
import json
import logging
import boto3
from botocore.exceptions import ClientError

log = logging.getLogger(__name__)

# ─── MODULE-LEVEL CACHE ───────────────────────────────────────────────────────
# Populated on first call. Persists for the lifetime of a warm Lambda container,
# so Secrets Manager is called at most once per cold start.
_cache: dict = {}

SECRET_NAME = os.environ.get("DSI_SECRET_NAME", "dsi/secrets")
AWS_REGION  = os.environ.get("AWS_REGION", "us-east-1")


def _is_lambda() -> bool:
    """True when running inside AWS Lambda."""
    return "AWS_LAMBDA_FUNCTION_NAME" in os.environ


def _load_from_secrets_manager() -> dict:
    """Fetch the DSI secret from AWS Secrets Manager and return as dict."""
    log.info(f"Fetching secret '{SECRET_NAME}' from Secrets Manager ({AWS_REGION})...")
    client = boto3.client("secretsmanager", region_name=AWS_REGION)
    try:
        resp = client.get_secret_value(SecretId=SECRET_NAME)
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "ResourceNotFoundException":
            raise RuntimeError(
                f"Secret '{SECRET_NAME}' not found. "
                "Run infra/create_secrets.sh to create it."
            ) from e
        if code == "AccessDeniedException":
            raise RuntimeError(
                f"Lambda role lacks secretsmanager:GetSecretValue on '{SECRET_NAME}'. "
                "Attach the policy in infra/iam_policy.json to the Lambda execution role."
            ) from e
        raise

    raw = resp.get("SecretString") or resp.get("SecretBinary", b"").decode()
    secrets = json.loads(raw)
    log.info("Secrets loaded from Secrets Manager")
    return secrets


def _load_from_env() -> dict:
    """Load secrets from environment variables (local dev fallback)."""
    log.info("Running locally — loading secrets from environment variables")
    missing = []
    for key in ("ANTHROPIC_API_KEY", "GITHUB_TOKEN"):
        if not os.environ.get(key):
            missing.append(key)
    if missing:
        raise RuntimeError(
            f"Missing environment variables for local run: {', '.join(missing)}\n"
            "Set them in your shell or in a .env file loaded before running."
        )
    return {
        "ANTHROPIC_API_KEY": os.environ["ANTHROPIC_API_KEY"],
        "GITHUB_TOKEN":      os.environ["GITHUB_TOKEN"],
    }


def get_secrets() -> dict:
    """
    Return the secrets dict. Uses cache after first call.
    Automatically chooses Secrets Manager (Lambda) or env vars (local).
    """
    global _cache
    if _cache:
        return _cache

    if _is_lambda():
        _cache = _load_from_secrets_manager()
    else:
        _cache = _load_from_env()

    return _cache


def get(key: str) -> str:
    """Convenience: get a single secret value by key."""
    return get_secrets()[key]
