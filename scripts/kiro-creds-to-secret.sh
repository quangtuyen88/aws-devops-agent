#!/usr/bin/env bash
#
# kiro-creds-to-secret.sh — extract the minimal Kiro OIDC credentials from the local kiro-cli
# SQLite DB and either write them to AWS Secrets Manager (default) or to a local file (-o).
#
# Why: the gateway's OIDC path (clientId/clientSecret present) needs NO profileArn. The full
# DB is ~68 MB (won't fit Secrets Manager's 64 KB limit), so we extract only the two tiny
# auth_kv rows and reshape them into the gateway's camelCase "AWS SSO JSON" format.
#
# The assembled JSON is the value injected (via the init container) into KIRO_CREDS_FILE.
# Secret values are NEVER printed to stdout; the JSON is piped to AWS / written 0600.
#
# Usage:
#   scripts/kiro-creds-to-secret.sh -p <name_prefix> -r <region>      # -> Secrets Manager
#   scripts/kiro-creds-to-secret.sh -s <secret-id>   -r <region>      # explicit secret id
#   scripts/kiro-creds-to-secret.sh -o kiro-creds.json                # local file (no AWS)
#
set -euo pipefail

DB_FILE=""
REGION="${AWS_REGION:-us-east-1}"
SECRET_ID=""
NAME_PREFIX=""
OUT_FILE=""

usage() {
  cat <<'EOF'
Usage: kiro-creds-to-secret.sh [options]

Extract Kiro OIDC credentials from the kiro-cli SQLite DB into the gateway's JSON format,
then push to AWS Secrets Manager (default) or write to a local file.

Options:
  -d, --db <path>          Path to kiro-cli data.sqlite3 (auto-detected if omitted).
  -r, --region <region>    AWS region (default: $AWS_REGION or us-east-1).
  -s, --secret-id <id>     Target Secrets Manager secret id/ARN.
  -p, --name-prefix <pfx>  Derive secret id as "<pfx>/inference/kiro-sso-credentials".
  -o, --out-file <path>    Write the JSON to a local 0600 file instead of calling AWS.
  -h, --help               Show this help and exit.

Exactly one destination is required: -o, or one of -s / -p. The secret container must already
exist (Terraform creates it) before a put. Secrets are never echoed to stdout.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
  -d | --db)
    [[ $# -ge 2 ]] || { echo "error: ${1} needs a value" >&2; exit 2; }
    DB_FILE="$2"; shift 2 ;;
  -r | --region)
    [[ $# -ge 2 ]] || { echo "error: ${1} needs a value" >&2; exit 2; }
    REGION="$2"; shift 2 ;;
  -s | --secret-id)
    [[ $# -ge 2 ]] || { echo "error: ${1} needs a value" >&2; exit 2; }
    SECRET_ID="$2"; shift 2 ;;
  -p | --name-prefix)
    [[ $# -ge 2 ]] || { echo "error: ${1} needs a value" >&2; exit 2; }
    NAME_PREFIX="$2"; shift 2 ;;
  -o | --out-file)
    [[ $# -ge 2 ]] || { echo "error: ${1} needs a value" >&2; exit 2; }
    OUT_FILE="$2"; shift 2 ;;
  -h | --help)
    usage; exit 0 ;;
  *)
    echo "error: unknown argument: ${1}" >&2; usage >&2; exit 2 ;;
  esac
done

# --- Tool checks ---
for tool in sqlite3 jq; do
  command -v "$tool" >/dev/null 2>&1 || { echo "error: required tool '${tool}' not found" >&2; exit 1; }
done

# --- Resolve destination ---
if [[ -n "${OUT_FILE}" ]]; then
  : # local file mode
elif [[ -n "${SECRET_ID}" ]]; then
  : # explicit secret id
elif [[ -n "${NAME_PREFIX}" ]]; then
  SECRET_ID="${NAME_PREFIX}/inference/kiro-sso-credentials"
else
  echo "error: provide a destination: -o <file>, or -s <secret-id>, or -p <name-prefix>" >&2
  usage >&2
  exit 2
fi
if [[ -z "${OUT_FILE}" ]]; then
  command -v aws >/dev/null 2>&1 || { echo "error: aws CLI not found (needed to put the secret)" >&2; exit 1; }
fi

# --- Locate the kiro-cli DB ---
if [[ -z "${DB_FILE}" ]]; then
  for c in \
    "${HOME}/Library/Application Support/kiro-cli/data.sqlite3" \
    "${HOME}/.local/share/kiro-cli/data.sqlite3" \
    "${HOME}/.local/share/amazon-q/data.sqlite3"; do
    [[ -f "$c" ]] && { DB_FILE="$c"; break; }
  done
fi
[[ -n "${DB_FILE}" && -f "${DB_FILE}" ]] || {
  echo "error: kiro-cli DB not found; pass it with -d <path>" >&2
  exit 1
}

# --- Read the two auth_kv rows (support both key-prefix variants) ---
read_kv() {
  local db="$1" suffix="$2" v
  v="$(sqlite3 "${db}" "select value from auth_kv where key='kirocli:odic:${suffix}';")"
  if [[ -z "${v}" ]]; then
    v="$(sqlite3 "${db}" "select value from auth_kv where key='codewhisperer:odic:${suffix}';")"
  fi
  printf '%s' "${v}"
}

TOKEN_JSON="$(read_kv "${DB_FILE}" "token")"
REG_JSON="$(read_kv "${DB_FILE}" "device-registration")"
[[ -n "${TOKEN_JSON}" ]] || { echo "error: no 'token' row in auth_kv (is kiro-cli logged in?)" >&2; exit 1; }
[[ -n "${REG_JSON}" ]] || { echo "error: no 'device-registration' row in auth_kv" >&2; exit 1; }

# profileArn lives in the state table (key 'api.codewhisperer.profile'). The Kiro API requires
# it for this account type even on the OIDC path, so include it when present.
PROFILE_ARN="$(
  sqlite3 "${DB_FILE}" "select value from state where key='api.codewhisperer.profile';" 2>/dev/null \
    | grep -oE 'arn:aws:codewhisperer:[a-z0-9-]+:[0-9]+:profile/[A-Za-z0-9]+' | head -1 || true
)"

# --- Reshape snake_case DB fields -> gateway camelCase OIDC JSON (Option 1 format) ---
CREDS_JSON="$(
  jq -n \
    --argjson t "${TOKEN_JSON}" \
    --argjson r "${REG_JSON}" \
    --arg profile_arn "${PROFILE_ARN}" \
    --arg fallback_region "${REGION}" \
    '{
      accessToken:  $t.access_token,
      refreshToken: $t.refresh_token,
      expiresAt:    $t.expires_at,
      region:       ($t.region // $r.region // $fallback_region),
      clientId:     $r.client_id,
      clientSecret: $r.client_secret
    }
    + (if $profile_arn != "" then { profileArn: $profile_arn } else {} end)'
)"

# Sanity: required fields present (checked as booleans, values never printed).
echo "${CREDS_JSON}" | jq -e \
  '(.accessToken|type=="string") and (.refreshToken|type=="string") and
   (.clientId|type=="string") and (.clientSecret|type=="string")' >/dev/null || {
  echo "error: extracted credentials are missing required fields" >&2
  exit 1
}

# --- Emit ---
if [[ -n "${OUT_FILE}" ]]; then
  ( umask 077; printf '%s' "${CREDS_JSON}" >"${OUT_FILE}" )
  echo "wrote OIDC credentials JSON -> ${OUT_FILE} (mode 0600). Keep it out of git."
else
  printf '%s' "${CREDS_JSON}" \
    | aws secretsmanager put-secret-value \
        --region "${REGION}" \
        --secret-id "${SECRET_ID}" \
        --secret-string file:///dev/stdin \
        --output text --query 'VersionId' \
    && echo "pushed credentials -> secret '${SECRET_ID}' (region ${REGION})."
fi
