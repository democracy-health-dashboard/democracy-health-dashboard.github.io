#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# create_secrets.sh
# Creates (or updates) the dsi/secrets secret in AWS Secrets Manager.
#
# Prerequisites:
#   - AWS CLI installed and configured (aws configure)
#   - Sufficient IAM permissions: secretsmanager:CreateSecret / PutSecretValue
#
# Usage:
#   chmod +x create_secrets.sh
#   ./create_secrets.sh
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SECRET_NAME="dsi/secrets"
REGION="${AWS_REGION:-us-east-1}"

echo ""
echo "═══════════════════════════════════════════════════════"
echo "  DSI Secrets Manager Setup"
echo "═══════════════════════════════════════════════════════"
echo ""

# ── Prompt for values ──────────────────────────────────────────────────────
read -rsp "  Enter ANTHROPIC_API_KEY (input hidden): " ANTHROPIC_KEY
echo ""
read -rsp "  Enter GITHUB_TOKEN (input hidden): " GITHUB_TOKEN
echo ""
echo ""

# ── Validate inputs ────────────────────────────────────────────────────────
if [[ -z "$ANTHROPIC_KEY" || -z "$GITHUB_TOKEN" ]]; then
  echo "✗ Both values are required. Aborting."
  exit 1
fi

# ── Build JSON payload ─────────────────────────────────────────────────────
SECRET_VALUE=$(cat <<EOF
{
  "ANTHROPIC_API_KEY": "${ANTHROPIC_KEY}",
  "GITHUB_TOKEN": "${GITHUB_TOKEN}"
}
EOF
)

# ── Create or update the secret ────────────────────────────────────────────
echo "  Checking if secret '${SECRET_NAME}' already exists in ${REGION}..."

if aws secretsmanager describe-secret \
     --secret-id "$SECRET_NAME" \
     --region "$REGION" \
     --output text > /dev/null 2>&1; then

  echo "  Secret exists — updating value..."
  aws secretsmanager put-secret-value \
    --secret-id "$SECRET_NAME" \
    --secret-string "$SECRET_VALUE" \
    --region "$REGION" \
    --output json | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  ✓ Updated: {d[\"ARN\"]}')"

else
  echo "  Secret not found — creating..."
  aws secretsmanager create-secret \
    --name "$SECRET_NAME" \
    --description "DSI monitoring agent credentials (Anthropic + GitHub)" \
    --secret-string "$SECRET_VALUE" \
    --region "$REGION" \
    --output json | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'  ✓ Created: {d[\"ARN\"]}')"
fi

# ── Print next steps ───────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════"
echo "  Next steps:"
echo ""
echo "  1. Note your secret ARN above."
echo "  2. In infra/iam_policy.json, replace:"
echo "       REGION     → ${REGION}"
echo "       ACCOUNT_ID → your 12-digit AWS account ID"
echo "     (Remove the KMS block if using the default key)"
echo ""
echo "  3. Attach the policy to your Lambda execution role:"
echo "       aws iam put-role-policy \\"
echo "         --role-name YOUR_LAMBDA_ROLE \\"
echo "         --policy-name DSISecretsAccess \\"
echo "         --policy-document file://infra/iam_policy.json"
echo ""
echo "  4. Deploy Lambda with SAM:"
echo "       cd infra && sam build && sam deploy --guided"
echo "═══════════════════════════════════════════════════════"
echo ""
