#!/usr/bin/env bash
#
# build-lambda.sh — build the UNIT-001 Lambda deployment package (the slack_devops_agent
# package + its runtime dependencies) and upload it to S3 at the key Terraform reads. The
# intake, worker, and reaper Lambdas all share this one zip; handlers are
# slack_devops_agent.entrypoints.lambda_{intake,worker,reaper}.lambda_handler.
#
# Dependencies are installed for the Lambda runtime platform (manylinux2014_x86_64, py3.12)
# so native wheels (pydantic-core) match Lambda, not your laptop.
#
# Usage:
#   scripts/build-lambda.sh -b <artifact-bucket> [-k <s3-key>] [-r <region>]
#
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"

REGION="${AWS_REGION:-us-east-1}"
BUCKET=""
S3_KEY="slack-devops-agent/unit-001.zip"
PY_VERSION="3.12"

usage() {
  cat <<'EOF'
Usage: build-lambda.sh -b <artifact-bucket> [-k <s3-key>] [-r <region>]

Build the Lambda deployment zip (slack_devops_agent + deps) and upload to S3.

Options:
  -b, --bucket <name>   S3 bucket to upload the artifact to (required).
  -k, --key <s3-key>    S3 key for the zip (default: slack-devops-agent/unit-001.zip).
  -r, --region <region> AWS region (default: $AWS_REGION or us-east-1).
  -h, --help            Show this help and exit.

Set the same values in deploy.env:
  LAMBDA_ARTIFACT_S3_BUCKET=<bucket>  LAMBDA_ARTIFACT_S3_KEY=<key>
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
  -b | --bucket) BUCKET="$2"; shift 2 ;;
  -k | --key)    S3_KEY="$2"; shift 2 ;;
  -r | --region) REGION="$2"; shift 2 ;;
  -h | --help)   usage; exit 0 ;;
  *) echo "error: unknown argument: ${1}" >&2; usage >&2; exit 2 ;;
  esac
done

[[ -n "${BUCKET}" ]] || { echo "error: -b/--bucket is required" >&2; exit 2; }
command -v aws >/dev/null 2>&1 || { echo "error: aws CLI not found on PATH" >&2; exit 1; }
command -v pip >/dev/null 2>&1 || command -v pip3 >/dev/null 2>&1 || {
  echo "error: pip not found on PATH" >&2; exit 1
}
PIP="$(command -v pip3 || command -v pip)"

BUILD_DIR="$(mktemp -d)"
ZIP_PATH="$(mktemp -u)/unit-001.zip"
mkdir -p "$(dirname "${ZIP_PATH}")"
trap 'rm -rf "${BUILD_DIR}" "$(dirname "${ZIP_PATH}")"' EXIT

echo "==> installing runtime dependencies for lambda (manylinux2014_x86_64, py${PY_VERSION})"
# Pull the same pinned deps as pyproject [project.dependencies]; target the Lambda platform.
"${PIP}" install \
  --target "${BUILD_DIR}" \
  --platform manylinux2014_x86_64 \
  --implementation cp \
  --python-version "${PY_VERSION}" \
  --only-binary=:all: --upgrade \
  "slack-bolt>=1.18.0" "pydantic>=2.6.0" "pydantic-settings>=2.2.0" \
  "boto3>=1.34.0" "httpx>=0.27.0" >/dev/null

echo "==> copying application package (src/slack_devops_agent)"
cp -R "${REPO_ROOT}/src/slack_devops_agent" "${BUILD_DIR}/slack_devops_agent"

echo "==> pruning caches and test artifacts"
find "${BUILD_DIR}" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "${BUILD_DIR}" -type d -name "*.dist-info" -prune -exec rm -rf {} +
find "${BUILD_DIR}" -type f -name "*.pyc" -delete

echo "==> zipping"
( cd "${BUILD_DIR}" && zip -qr "${ZIP_PATH}" . )
SIZE="$(du -h "${ZIP_PATH}" | cut -f1)"
echo "    built ${ZIP_PATH} (${SIZE})"

echo "==> ensuring artifact bucket s3://${BUCKET}"
if ! aws s3api head-bucket --bucket "${BUCKET}" >/dev/null 2>&1; then
  if [[ "${REGION}" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" >/dev/null
  else
    aws s3api create-bucket --bucket "${BUCKET}" --region "${REGION}" \
      --create-bucket-configuration "LocationConstraint=${REGION}" >/dev/null
  fi
fi

echo "==> uploading to s3://${BUCKET}/${S3_KEY}"
aws s3 cp "${ZIP_PATH}" "s3://${BUCKET}/${S3_KEY}" --region "${REGION}"

echo "==> done"
echo "    LAMBDA_ARTIFACT_S3_BUCKET=${BUCKET}"
echo "    LAMBDA_ARTIFACT_S3_KEY=${S3_KEY}"
