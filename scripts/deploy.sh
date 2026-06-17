#!/usr/bin/env bash
#
# deploy.sh — plan (default) or apply the Slack DevOps Agent (UNIT-001) Terraform stack
# against an EXISTING VPC/subnets/SG, sourcing non-secret IDs + backend config from a
# gitignored env file (default ./deploy.env).
#
# SAFETY: plan-only by DEFAULT. `terraform apply` runs ONLY with the explicit --apply flag.
# There is intentionally NO destroy command here.
#
# Usage:
#   scripts/deploy.sh [-e <env-file>] [--apply] [--auto-approve]
#
set -euo pipefail

# --- Locations -------------------------------------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"
TF_DIR="${REPO_ROOT}/infra/terraform"

# --- Defaults --------------------------------------------------------------
ENV_FILE="${REPO_ROOT}/deploy.env"
DO_APPLY="false"
AUTO_APPROVE="false"
LOAD_KIRO_CREDS="false"

usage() {
  cat <<'EOF'
Usage: deploy.sh [options]

Plan (default) or apply the UNIT-001 Terraform stack against an existing VPC.

Options:
  -e, --env-file <path>   Env file to source (default: ./deploy.env at repo root).
      --apply             Run `terraform apply` instead of the default plan-only run.
      --auto-approve      With --apply, skip the interactive approval prompt.
      --load-kiro-creds   After a successful apply, extract Kiro creds from the local
                          kiro-cli DB and push them to the gateway secret (requires --apply,
                          aws CLI, sqlite3, jq). Runs scripts/kiro-creds-to-secret.sh.
  -h, --help              Show this help and exit.

The env file must export the existing network IDs and backend config; see
scripts/deploy.env.example for every supported variable. Secrets are NEVER set here —
they live in AWS Secrets Manager and are injected at runtime.
EOF
}

# --- Arg parsing -----------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
  -e | --env-file)
    [[ $# -ge 2 ]] || {
      echo "error: ${1} requires a path argument" >&2
      exit 2
    }
    ENV_FILE="$2"
    shift 2
    ;;
  --apply)
    DO_APPLY="true"
    shift
    ;;
  --auto-approve)
    AUTO_APPROVE="true"
    shift
    ;;
  --load-kiro-creds)
    LOAD_KIRO_CREDS="true"
    shift
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    echo "error: unknown argument: ${1}" >&2
    usage >&2
    exit 2
    ;;
  esac
done

# --- Source the env file ---------------------------------------------------
if [[ "${LOAD_KIRO_CREDS}" == "true" && "${DO_APPLY}" != "true" ]]; then
  echo "error: --load-kiro-creds requires --apply (the secret container must exist first)." >&2
  echo "       Run an apply, or call scripts/kiro-creds-to-secret.sh directly." >&2
  exit 2
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "error: env file not found: ${ENV_FILE}" >&2
  echo "       copy scripts/deploy.env.example to ${ENV_FILE} and fill it in." >&2
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "${ENV_FILE}"
set +a
# --- Validate required inputs ----------------------------------------------
require() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    echo "error: required variable '${name}' is not set in ${ENV_FILE}" >&2
    exit 1
  fi
}

require "AWS_REGION"
require "NAME_PREFIX"
require "EXISTING_VPC_ID"
require "EXISTING_PRIVATE_SUBNET_IDS"
require "EXISTING_SECURITY_GROUP_IDS"
require "TF_BACKEND_BUCKET"
require "TF_BACKEND_KEY"
require "TF_BACKEND_REGION"
require "TF_BACKEND_DYNAMODB_TABLE"

# --- Map env -> TF_VAR_* ---------------------------------------------------
# Existing-VPC mode is implied by this script's purpose; allow override via USE_EXISTING_NETWORK.
export TF_VAR_use_existing_network="${USE_EXISTING_NETWORK:-true}"
export TF_VAR_aws_region="${AWS_REGION}"
export TF_VAR_name_prefix="${NAME_PREFIX}"
export TF_VAR_existing_vpc_id="${EXISTING_VPC_ID}"
# List-typed TF vars must be HCL/JSON list strings, e.g. '["subnet-a","subnet-b"]'
# (set in that form in the env file — see scripts/deploy.env.example).
export TF_VAR_existing_private_subnet_ids="${EXISTING_PRIVATE_SUBNET_IDS}"
export TF_VAR_existing_security_group_ids="${EXISTING_SECURITY_GROUP_IDS}"

# Optional passthroughs — only export when present so TF defaults otherwise apply.
[[ -n "${ENVIRONMENT:-}" ]] && export TF_VAR_environment="${ENVIRONMENT}"
[[ -n "${EXISTING_NAT_GATEWAY:-}" ]] && export TF_VAR_existing_nat_gateway="${EXISTING_NAT_GATEWAY}"
[[ -n "${EXISTING_ALB:-}" ]] && export TF_VAR_existing_alb="${EXISTING_ALB}"
[[ -n "${EXISTING_ALB_LISTENER_ARN:-}" ]] && export TF_VAR_existing_alb_listener_arn="${EXISTING_ALB_LISTENER_ARN}"
[[ -n "${CREATE_SQS_ENDPOINT:-}" ]] && export TF_VAR_create_sqs_endpoint="${CREATE_SQS_ENDPOINT}"
[[ -n "${CREATE_SECRETSMANAGER_ENDPOINT:-}" ]] && export TF_VAR_create_secretsmanager_endpoint="${CREATE_SECRETSMANAGER_ENDPOINT}"
[[ -n "${CREATE_LOGS_ENDPOINT:-}" ]] && export TF_VAR_create_logs_endpoint="${CREATE_LOGS_ENDPOINT}"
[[ -n "${CREATE_ECR_API_ENDPOINT:-}" ]] && export TF_VAR_create_ecr_api_endpoint="${CREATE_ECR_API_ENDPOINT}"
[[ -n "${CREATE_ECR_DKR_ENDPOINT:-}" ]] && export TF_VAR_create_ecr_dkr_endpoint="${CREATE_ECR_DKR_ENDPOINT}"
[[ -n "${CREATE_BEDROCK_ENDPOINT:-}" ]] && export TF_VAR_create_bedrock_endpoint="${CREATE_BEDROCK_ENDPOINT}"
[[ -n "${GATEWAY_IMAGE:-}" ]] && export TF_VAR_gateway_image="${GATEWAY_IMAGE}"
[[ -n "${GATEWAY_CERTIFICATE_ARN:-}" ]] && export TF_VAR_gateway_certificate_arn="${GATEWAY_CERTIFICATE_ARN}"
[[ -n "${LAMBDA_ARTIFACT_S3_BUCKET:-}" ]] && export TF_VAR_lambda_artifact_s3_bucket="${LAMBDA_ARTIFACT_S3_BUCKET}"
[[ -n "${LAMBDA_ARTIFACT_S3_KEY:-}" ]] && export TF_VAR_lambda_artifact_s3_key="${LAMBDA_ARTIFACT_S3_KEY}"

# --- Run terraform ---------------------------------------------------------
cd "${TF_DIR}"

echo "==> terraform init (backend: s3://${TF_BACKEND_BUCKET}/${TF_BACKEND_KEY})"
terraform init \
  -backend-config="bucket=${TF_BACKEND_BUCKET}" \
  -backend-config="key=${TF_BACKEND_KEY}" \
  -backend-config="region=${TF_BACKEND_REGION}" \
  -backend-config="dynamodb_table=${TF_BACKEND_DYNAMODB_TABLE}" \
  -input=false

if [[ "${DO_APPLY}" == "true" ]]; then
  echo "==> terraform apply (EXPLICIT --apply)"
  if [[ "${AUTO_APPROVE}" == "true" ]]; then
    terraform apply -input=false -auto-approve
  else
    terraform apply -input=false
  fi

  if [[ "${LOAD_KIRO_CREDS}" == "true" ]]; then
    echo "==> loading Kiro credentials into the gateway secret (post-apply)"
    "${SCRIPT_DIR}/kiro-creds-to-secret.sh" -p "${NAME_PREFIX}" -r "${AWS_REGION}"
  fi
else
  echo "==> terraform plan (default; pass --apply to apply)"
  terraform plan -input=false
fi
