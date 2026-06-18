#!/usr/bin/env bash
#
# load-secrets.sh — read application secrets from a gitignored .env file and push each one
# into the AWS Secrets Manager container Terraform created (§4.1). Run AFTER a successful
# apply (the containers must exist first). Kiro SSO credentials are NOT here — they come from
# the local kiro-cli DB via kiro-creds-to-secret.sh.
#
# SAFETY: secret values are NEVER printed to stdout. Empty/unset values are skipped (the
# container is left untouched), so partially-filled .env files don't clobber existing secrets.
#
# Usage:
#   scripts/load-secrets.sh [-e <env-file>] [-p <name_prefix>] [-r <region>]
#
set -euo pipefail

# --- Locations -------------------------------------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"

# --- Defaults --------------------------------------------------------------
ENV_FILE="${REPO_ROOT}/.env"
NAME_PREFIX="${NAME_PREFIX:-slack-devops-agent}"
REGION="${AWS_REGION:-us-east-1}"

usage() {
  cat <<'EOF'
Usage: load-secrets.sh [options]

Read application secrets from a .env file and push each into its AWS Secrets Manager
container (created by Terraform). Run after a successful apply.

Options:
  -e, --env-file <path>     .env file to read (default: ./.env at repo root).
  -p, --name-prefix <pfx>   Terraform name_prefix (default: $NAME_PREFIX or slack-devops-agent).
  -r, --region <region>     AWS region (default: $AWS_REGION or us-east-1).
  -h, --help                Show this help and exit.

Secret values are never printed. Empty values in the .env file are skipped (the existing
secret is left untouched). Kiro SSO credentials are loaded separately by kiro-creds-to-secret.sh.
EOF
}

# --- Arg parsing -----------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
  -e | --env-file)
    [[ $# -ge 2 ]] || { echo "error: ${1} requires a path argument" >&2; exit 2; }
    ENV_FILE="$2"; shift 2 ;;
  -p | --name-prefix)
    [[ $# -ge 2 ]] || { echo "error: ${1} requires an argument" >&2; exit 2; }
    NAME_PREFIX="$2"; shift 2 ;;
  -r | --region)
    [[ $# -ge 2 ]] || { echo "error: ${1} requires an argument" >&2; exit 2; }
    REGION="$2"; shift 2 ;;
  -h | --help)
    usage; exit 0 ;;
  *)
    echo "error: unknown argument: ${1}" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "error: env file not found: ${ENV_FILE}" >&2
  echo "       copy .env.example to ${ENV_FILE} and fill in the secrets." >&2
  exit 1
fi

command -v aws >/dev/null 2>&1 || { echo "error: aws CLI not found on PATH" >&2; exit 1; }

# --- Source the env file (export so the named vars are visible below) -------
set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a

# --- Push one secret -------------------------------------------------------
# put_secret <ENV_VAR_NAME> <secret-suffix>
#   secret id = "<name_prefix>/<secret-suffix>" (matches modules/security/main.tf)
#   value piped via --secret-string file:///dev/stdin so it never appears in argv/ps.
put_secret() {
  local var_name="$1" suffix="$2"
  local value="${!var_name:-}"
  local secret_id="${NAME_PREFIX}/${suffix}"

  if [[ -z "${value}" ]]; then
    echo "  skip  ${secret_id}  (${var_name} empty/unset)"
    return 0
  fi

  printf '%s' "${value}" \
    | aws secretsmanager put-secret-value \
        --region "${REGION}" \
        --secret-id "${secret_id}" \
        --secret-string file:///dev/stdin \
        --output text --query 'VersionId' >/dev/null

  echo "  ok    ${secret_id}  (from ${var_name})"
}

echo "==> loading application secrets from ${ENV_FILE} into Secrets Manager (${REGION})"

# Map .env keys -> Secrets Manager containers (modules/security/main.tf for_each).
# Kiro SSO (inference/kiro-sso-credentials) is handled by kiro-creds-to-secret.sh, not here.
put_secret SLACK_BOT_TOKEN      "slack/bot-token"
put_secret SLACK_SIGNING_SECRET "slack/signing-secret"
put_secret PROXY_API_KEY        "inference/kiro-gateway-proxy-key"
put_secret MCP_API_KEY          "mcp/aws-knowledge-credential"

echo "==> done"
