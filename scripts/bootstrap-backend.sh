#!/usr/bin/env bash
#
# bootstrap-backend.sh — create the Terraform remote-state backend (S3 bucket + DynamoDB lock
# table) ONCE, out of band, before the first `terraform init`. Idempotent: re-running is safe
# (already-exists is treated as success). This creates ONLY the state backend — it deploys none
# of the application stack.
#
# Usage:
#   scripts/bootstrap-backend.sh -b <state-bucket> -t <lock-table> [-r <region>]
#
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
BUCKET=""
TABLE=""

usage() {
  cat <<'EOF'
Usage: bootstrap-backend.sh -b <state-bucket> -t <lock-table> [-r <region>]

Create the Terraform remote-state backend (S3 bucket + DynamoDB lock table). Idempotent.

Options:
  -b, --bucket <name>    S3 bucket for terraform state (must be globally unique).
  -t, --table  <name>    DynamoDB table for state locking (hash key: LockID).
  -r, --region <region>  AWS region (default: $AWS_REGION or us-east-1).
  -h, --help             Show this help and exit.

After this runs, set in deploy.env:
  TF_BACKEND_BUCKET=<bucket>  TF_BACKEND_DYNAMODB_TABLE=<table>  TF_BACKEND_REGION=<region>
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
  -b | --bucket) BUCKET="$2"; shift 2 ;;
  -t | --table)  TABLE="$2";  shift 2 ;;
  -r | --region) REGION="$2"; shift 2 ;;
  -h | --help)   usage; exit 0 ;;
  *) echo "error: unknown argument: ${1}" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "${BUCKET}" ]] || { echo "error: -b/--bucket is required" >&2; exit 2; }
[[ -n "${TABLE}"  ]] || { echo "error: -t/--table is required"  >&2; exit 2; }
command -v aws >/dev/null 2>&1 || { echo "error: aws CLI not found on PATH" >&2; exit 1; }

echo "==> region: ${REGION}"

# --- S3 state bucket -------------------------------------------------------
if aws s3api head-bucket --bucket "${BUCKET}" >/dev/null 2>&1; then
  echo "  ok    s3://${BUCKET} already exists"
else
  echo "  create s3://${BUCKET}"
  if [[ "${REGION}" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" >/dev/null
  else
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" \
      --create-bucket-configuration "LocationConstraint=${REGION}" >/dev/null
  fi
fi

echo "  set   block-public-access + versioning + default encryption"
aws s3api put-public-access-block --bucket "${BUCKET}" \
  --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket "${BUCKET}" \
  --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket "${BUCKET}" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

# --- DynamoDB lock table ---------------------------------------------------
if aws dynamodb describe-table --table-name "${TABLE}" --region "${REGION}" >/dev/null 2>&1; then
  echo "  ok    dynamodb table ${TABLE} already exists"
else
  echo "  create dynamodb table ${TABLE}"
  aws dynamodb create-table --table-name "${TABLE}" --region "${REGION}" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST >/dev/null
  echo "  wait  table to become ACTIVE"
  aws dynamodb wait table-exists --table-name "${TABLE}" --region "${REGION}"
fi

echo "==> backend ready"
echo "    TF_BACKEND_BUCKET=${BUCKET}"
echo "    TF_BACKEND_DYNAMODB_TABLE=${TABLE}"
echo "    TF_BACKEND_REGION=${REGION}"
