# Deploy to an existing VPC — step-by-step runbook

End-to-end guide to deploy the Slack DevOps Agent (UNIT-001) into a **pre-existing VPC**, with
the stack **creating its own internal ALB**, and all application secrets loaded **automatically
from `.env`**.

This is the operational runbook. For architecture and cost detail see [`DEPLOYMENT.md`](./DEPLOYMENT.md).

> **Policy:** every `terraform apply` and AWS-mutating command here is run **manually by you**.
> Plan is the default; apply needs an explicit flag.

---

## 0. Prerequisites (one-time, on the operator machine)

- AWS CLI v2, authenticated to the target account (`aws sts get-caller-identity` works).
- Terraform ≥ 1.6, Python 3.12, `uv`, `pip`, `zip`, `docker`.
- A logged-in **`kiro-cli`** (for the Kiro inference credentials) + `sqlite3`, `jq`.
- The existing-network IDs from whoever owns the VPC:
  - VPC id — `vpc-…`
  - ≥ 2 **private** subnet ids in different AZs — `subnet-…`
  - security group id(s) for in-VPC compute — `sg-…`
  - whether to reuse the VPC's NAT (`EXISTING_NAT_GATEWAY`)

---

## 1. Fill in `.env` (application secrets)

Secrets live **only** in `.env` (gitignored). They are pushed to AWS Secrets Manager
automatically by the deploy in step 6 — you never run `put-secret-value` by hand.

```bash
cp .env.example .env
$EDITOR .env
```

| `.env` key | Where it comes from |
|---|---|
| `SLACK_BOT_TOKEN` | Slack app → Bot User OAuth Token (`xoxb-…`) |
| `SLACK_SIGNING_SECRET` | Slack app → Basic Information → Signing Secret |
| `PROXY_API_KEY` | **You invent it** — a shared secret between the worker and your kiro-gateway. Generate: `openssl rand -hex 32` |
| `MCP_API_KEY` | **Leave empty** for the public AWS Knowledge MCP (it needs no key). Only set it if `MCP_BASE_URL` points at a private, keyed endpoint. |

> Kiro SSO credentials are **not** in `.env` — they come from your `kiro-cli` login and are
> loaded separately in step 6 (`--load-kiro-creds`).

---

## 2. Create the Terraform state backend (one-time)

The remote state (S3 bucket + DynamoDB lock table) must exist before `terraform init`.

```bash
scripts/bootstrap-backend.sh \
  -b my-terraform-state-bucket \
  -t terraform-state-lock \
  -r us-east-1
```

Idempotent — safe to re-run. Note the three values it prints; they go into `deploy.env` (step 5).

---

## 3. Request an ACM certificate (for the created ALB)

The stack creates an **internal HTTPS ALB**, which needs an ACM cert in the same region.

```bash
aws acm request-certificate \
  --domain-name kiro-gateway.internal.yourcorp.com \
  --validation-method DNS --region us-east-1
# Add the CNAME it returns to your DNS, wait for status ISSUED, then grab the ARN:
aws acm list-certificates --region us-east-1 \
  --query "CertificateSummaryList[?DomainName=='kiro-gateway.internal.yourcorp.com'].CertificateArn" \
  --output text
```

Keep the ARN for `GATEWAY_CERTIFICATE_ARN` (step 5).

---

## 4. Build & push the two artifacts

**4a. Lambda zip → S3** (intake + worker + reaper share one zip):

```bash
# Run the quality gate first
uv sync --extra dev
uv run ruff check . && uv run mypy && uv run pytest

scripts/build-lambda.sh \
  -b my-artifacts-bucket \
  -k slack-devops-agent/unit-001.zip \
  -r us-east-1
```

**4b. kiro-gateway image → ECR** (unmodified upstream, AGPL boundary — see
[`DEPLOYMENT.md` §6.1](./DEPLOYMENT.md#61-build--push-the-kiro-gateway-image-docker)):

```bash
export AWS_REGION="us-east-1"
export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export IMAGE_TAG="1.0.0"
export ECR_IMAGE="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/kiro-gateway:${IMAGE_TAG}"

aws ecr create-repository --repository-name kiro-gateway --region "${AWS_REGION}" \
  --image-scanning-configuration scanOnPush=true || true
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin \
      "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
docker pull "ghcr.io/jwadow/kiro-gateway:${IMAGE_TAG}"
docker tag  "ghcr.io/jwadow/kiro-gateway:${IMAGE_TAG}" "${ECR_IMAGE}"
docker push "${ECR_IMAGE}"
echo "${ECR_IMAGE}"   # -> GATEWAY_IMAGE in deploy.env
```

---

## 5. Fill in `deploy.env` (non-secret IDs + config)

`deploy.env` is gitignored and holds **only** non-secret IDs and config — never secrets.

```bash
cp scripts/deploy.env.example deploy.env
$EDITOR deploy.env
```

```bash
# --- existing network ---
AWS_REGION="us-east-1"
NAME_PREFIX="slack-devops-agent"
USE_EXISTING_NETWORK="true"
EXISTING_VPC_ID="vpc-0abc…"
EXISTING_PRIVATE_SUBNET_IDS='["subnet-0aaa…","subnet-0bbb…"]'   # ≥2, different AZs
EXISTING_SECURITY_GROUP_IDS='["sg-0abc…"]'
EXISTING_NAT_GATEWAY="false"        # true to reuse the VPC's NAT instead of creating one

# --- state backend (from step 2) ---
TF_BACKEND_BUCKET="my-terraform-state-bucket"
TF_BACKEND_KEY="slack-devops-agent/unit-001/terraform.tfstate"
TF_BACKEND_REGION="us-east-1"
TF_BACKEND_DYNAMODB_TABLE="terraform-state-lock"

# --- artifacts (from steps 3 & 4) ---
GATEWAY_CERTIFICATE_ARN="arn:aws:acm:us-east-1:…:certificate/…"
GATEWAY_IMAGE="…dkr.ecr.us-east-1.amazonaws.com/kiro-gateway:1.0.0"
LAMBDA_ARTIFACT_S3_BUCKET="my-artifacts-bucket"
LAMBDA_ARTIFACT_S3_KEY="slack-devops-agent/unit-001.zip"

# Leave EXISTING_ALB unset → the stack creates the internal ALB (create-ALB mode).
```

---

## 6. Plan, then apply

```bash
# Plan — read it before applying (safe, read-only against state).
scripts/deploy.sh

# Apply + auto-load secrets from .env + load Kiro creds — YOUR explicit manual step.
scripts/deploy.sh --apply --load-kiro-creds
```

On `--apply` the script runs, in order:

1. `terraform apply` — provisions Lambdas, SQS, DynamoDB, the ECS gateway, the ALB, IAM,
   and the (empty) Secrets Manager containers.
2. **`scripts/load-secrets.sh`** — reads `.env` and pushes `SLACK_BOT_TOKEN`,
   `SLACK_SIGNING_SECRET`, `PROXY_API_KEY`, and `MCP_API_KEY` (if set) into their containers.
   Empty values are skipped; values are never printed.
3. **`scripts/kiro-creds-to-secret.sh`** — extracts Kiro OIDC creds from your local `kiro-cli`
   DB and pushes them to the gateway secret.

> Flags: `--no-load-secrets` skips step 2; `--secrets-env-file <path>` reads a different env file
> (default `./.env`); `--auto-approve` skips the interactive apply prompt.

---

## 7. Wire up Slack & verify

```bash
cd infra/terraform && terraform output
```

- `slack_events_api_endpoint` → set as the Slack app **Event Subscriptions → Request URL**;
  confirm URL verification succeeds.
- `gateway_internal_endpoint` → internal ALB DNS fronting kiro-gateway (private; for diagnostics).

Then run the post-deploy checks ([`DEPLOYMENT.md` §7](./DEPLOYMENT.md#7-post-deploy-verification)):
`@mention` the bot in an allowlisted channel, expect ack < 3 s → heartbeat → cited answer;
react 👍/👎; confirm a non-allowlisted channel gets the not-designated reply.

---

## Quick reference — full sequence

```bash
# one-time
cp .env.example .env && $EDITOR .env
scripts/bootstrap-backend.sh -b my-tf-state -t terraform-state-lock -r us-east-1
# request + validate ACM cert, capture ARN

# per-release
uv sync --extra dev && uv run ruff check . && uv run mypy && uv run pytest
scripts/build-lambda.sh -b my-artifacts-bucket -r us-east-1
# build + push kiro-gateway image to ECR

cp scripts/deploy.env.example deploy.env && $EDITOR deploy.env
scripts/deploy.sh                              # plan
scripts/deploy.sh --apply --load-kiro-creds    # apply + secrets + kiro creds

cd infra/terraform && terraform output         # wire Slack Request URL
```

---

## Rollback / teardown

`scripts/deploy.sh` intentionally has **no destroy** path. To tear down app resources:

```bash
cd infra/terraform && terraform destroy
```

The existing VPC, subnets, SG, and NAT are referenced via **data sources only** — `terraform
destroy` removes only app-created resources (Lambdas, SQS, DynamoDB, ECS service/task, the ALB
**this stack created**, the VPC endpoints it created, IAM, secrets) and can **never** delete the
borrowed network.
