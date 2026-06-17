# Deployment Guide — Slack DevOps Agent (UNIT-001)

How to deploy the Slack DevOps Agent bot to AWS. The application code lives in
`src/slack_devops_agent/`; infrastructure-as-code lives in `infra/terraform/`.

> **Policy reminder:** This repo authors and *validates* Terraform only. All
> `terraform apply` and other mutating commands are run **manually by you** — the
> agent never applies infrastructure.

---

## 1. Architecture recap

One deployable artifact, multiple runtime roles (all in a single AWS account/region):

| Role | Service | Purpose |
|------|---------|---------|
| Intake | API Gateway (HTTP API) → Lambda | Receive Slack events + reactions, ack < 3s, enqueue |
| Worker | SQS → Lambda | Run the agent loop, ground via MCP, compose + post the answer |
| Reaper | EventBridge → Lambda | Reclaim stale jobs, post failure messages |
| Inference gateway | ECS Fargate (2 tasks, Multi-AZ) | Self-hosted **kiro-gateway** (Kiro primary) |
| State | DynamoDB | ProcessingJob (de-dup/lease), usage counter, feedback, config |
| Secrets | Secrets Manager | Slack tokens, `PROXY_API_KEY`, Bedrock model ARNs |
| Observability | CloudWatch | Structured logs (correlation-id), metrics, alarms |

Inference: **Kiro-gateway primary** (OpenAI-compatible `/v1/chat/completions`) with
**Amazon Bedrock as a config-flip alternate** behind the CMP-003 seam.

---

## 2. Prerequisites

- An AWS account + a region (e.g. `us-east-1`), with admin or a deploy role.
- Terraform >= 1.6, AWS CLI v2, Python 3.12, `uv`.
- Remote state backend: an S3 bucket + a DynamoDB lock table (create once, out of band).
- A **Slack app** (see §3).
- A **Kiro subscription** with credentials for the kiro-gateway (Builder ID or
  corporate SSO), per the kiro-gateway README.
- Bedrock model access enabled in the region (for the failover path).

> ⚠️ **Licensing:** kiro-gateway is **AGPL-3.0**. Per the recorded decision, deploy it
> **unmodified** as an external container (`ghcr.io/jwadow/kiro-gateway`). Do not fork
> or vendor it into this repo.

---

## 3. Create the Slack app

1. Create a Slack app (from manifest or scratch) in your workspace.
2. **Scopes (Bot Token):** `app_mentions:read`, `chat:write`, `reactions:read`,
   `channels:history` (for thread-context fetch), `groups:history` if private channels.
3. **Event subscriptions:** subscribe to `app_mention` and `reaction_added` /
   `reaction_removed`. Point the Request URL at the API Gateway intake endpoint
   (you'll get it from `terraform output` after the first apply — Slack URL
   verification is handled by the intake handler).
4. **Verify the subscription scope** — confirm only `app_mention` (+ reactions) is
   delivered, not the broad `message` event (flagged in code review).
5. Note the **Bot User OAuth Token** (`xoxb-…`) and the **Signing Secret**.
6. Install the app to the workspace and invite it to your allowlisted channel(s).

---

## 4. Populate secrets

Create these in AWS Secrets Manager (names are configurable via Terraform vars):

| Secret | Contents |
|--------|----------|
| `slack/bot-token` | Slack Bot User OAuth token (`xoxb-…`) |
| `slack/signing-secret` | Slack signing secret (request verification) |
| `inference/proxy-api-key` | The kiro-gateway `PROXY_API_KEY` you set |
| `inference/kiro-credentials` | Kiro OIDC credentials JSON (see §6.2) — auto-extracted from your kiro-cli login by `scripts/kiro-creds-to-secret.sh`. Terraform names it `<name_prefix>/inference/kiro-sso-credentials`. |
| `mcp/auth` | Auth for the hosted `aws-knowledge-mcp-server` (if required) |

Bedrock needs no secret — access is via the worker's IAM role; set the allowed model
ARNs through the `bedrock_model_arns` Terraform variable.

---

## 5. Deploy the infrastructure (manual)

```bash
cd infra/terraform

# 1. Configure the remote backend (S3 + DynamoDB lock)
cp backend.hcl.example backend.hcl   # edit bucket / table / region
cp terraform.tfvars.example terraform.tfvars   # edit region, prefixes, allowlist, ARNs

# 2. Initialise with the backend
terraform init -backend-config=backend.hcl

# 3. Review the plan — READ IT before applying
terraform plan -out tfplan

# 4. Apply (this is YOUR manual step — the agent never applies)
terraform apply tfplan

# 5. Capture outputs (API GW URL, etc.)
terraform output
```

The 9 modules deploy: `networking`, `security`, `data`, `messaging`,
`compute-intake`, `compute-worker`, `recovery`, `gateway`, `observability`.

> The CI/validation-only checks are `terraform fmt -check -recursive` and
> `terraform validate` (run with `terraform init -backend=false`). These never touch
> live state.

### 5.1 Existing-VPC / existing-ALB mode (destroy-safe)

By default the stack **creates and owns** the VPC, NAT, subnets, and the internal ALB. To
deploy into a **pre-existing** network instead, flip `use_existing_network = true` and supply
the IDs:

| Variable | Type | Purpose |
|---|---|---|
| `use_existing_network` | bool (default `false`) | Consume an existing VPC instead of creating one |
| `existing_vpc_id` | string | ID of the pre-existing VPC |
| `existing_private_subnet_ids` | list(string) | Private subnets for the worker Lambda + Fargate |
| `existing_security_group_ids` | list(string) | Security group(s) for in-VPC compute |
| `existing_nat_gateway` | bool (default `false`) | Reuse the existing VPC's NAT (skip creating one) |
| `existing_alb` | bool (default `false`) | Add a listener rule to an existing ALB instead of creating one |
| `existing_alb_listener_arn` | string | ARN of the existing ALB HTTPS listener to attach the rule to |

> **🔒 Destroy-safety guarantee.** When these toggles are `true`, the pre-existing VPC,
> subnets, security groups, NAT, and ALB are referenced **only via Terraform data sources /
> by-ID** (`data.aws_vpc`, `data.aws_subnet`, `data.aws_security_group`,
> `data.aws_route_tables`, `data.aws_lb`, `data.aws_lb_listener`) — they are **never** declared
> as managed `resource` blocks. Terraform therefore does not own them, and `terraform destroy`
> removes **only app-created resources** (Lambdas, SQS, DynamoDB, ECS service/task, the VPC
> endpoints we created, the endpoint SG, the listener rule we added, IAM, secrets). It can
> **never** delete the borrowed VPC, subnets, SG, NAT, or ALB.

**Per-endpoint VPC endpoint toggles.** Each interface endpoint is individually conditional
(`count = var.X ? 1 : 0`). DynamoDB and S3 stay as **free gateway endpoints** (always created,
not toggled).

| Variable | Default | Endpoint |
|---|---|---|
| `create_sqs_endpoint` | `true` | SQS |
| `create_secretsmanager_endpoint` | `true` | Secrets Manager |
| `create_logs_endpoint` | `true` | CloudWatch Logs |
| `create_ecr_api_endpoint` | `true` | ECR API |
| `create_ecr_dkr_endpoint` | `true` | ECR Docker (dkr) |
| `create_bedrock_endpoint` | **`false`** | Bedrock runtime |

> `create_bedrock_endpoint` defaults to **false**: Bedrock is only the failover inference path,
> so its traffic **egresses via NAT** unless compliance requires PrivateLink — in which case set
> it to `true` to keep Bedrock calls on a private interface endpoint (adds ~$7.30/AZ/mo).

### 5.2 One-command deploy: `scripts/deploy.sh`

`scripts/deploy.sh` wraps the existing-VPC flow. It sources a **gitignored** env file (default
`./deploy.env`, override with `-e`), maps the values to `TF_VAR_*`, runs `terraform init` with
the S3 backend config, and then **plans by default**. `terraform apply` runs **only** with the
explicit `--apply` flag — there is intentionally no destroy command.

```bash
# 1. Create your env file from the template (it is gitignored — never commit it).
cp scripts/deploy.env.example deploy.env
$EDITOR deploy.env     # fill in region, name_prefix, existing VPC/subnet/SG IDs, backend

# 2. Plan (default — safe, read-only against your state).
scripts/deploy.sh                      # uses ./deploy.env
scripts/deploy.sh -e prod.deploy.env   # use a different env file

# 3. Apply — YOUR explicit manual step (the agent never applies).
scripts/deploy.sh --apply
scripts/deploy.sh --apply --auto-approve
```

`deploy.env` holds **only non-secret IDs + backend config**. Application secrets (Slack tokens,
`PROXY_API_KEY`, Kiro SSO) live in AWS Secrets Manager and are injected at runtime — never put
them in this file. List values (`EXISTING_PRIVATE_SUBNET_IDS`, `EXISTING_SECURITY_GROUP_IDS`)
must be HCL/JSON list strings, e.g. `'["subnet-a","subnet-b"]'`. See
`scripts/deploy.env.example` for every supported variable.

---

## 6. Package and ship the application

The bot is a Python 3.12 package. Build the Lambda artifact(s) and the gateway image:

```bash
# From repo root — run the quality gate first
uv sync --extra dev
uv run ruff check . && uv run mypy && uv run pytest

# Build the Lambda deployment package (zip of src/ + deps) — wire to your CI,
# or use the build target referenced in the compute-* Terraform modules.
```

- **Lambdas (intake/worker/reaper):** packaged from `src/slack_devops_agent/`; the
  three entrypoints are `entrypoints/lambda_intake.py`, `lambda_worker.py`,
  `lambda_reaper.py`.
- **kiro-gateway:** deploy the **unmodified upstream image** to the ECS Fargate
  service created by the `gateway` module — build/push it per §6.1, and load the Kiro
  credentials per §6.2 (`PROXY_API_KEY` + the OIDC creds JSON are injected at runtime).

Set the inference backend selection (Kiro primary, Bedrock alternate) via the
CMP-003 provider config / environment variables.

### 6.1 Build & push the kiro-gateway image (Docker)

The `gateway` module runs the **unmodified upstream kiro-gateway** container on ECS Fargate.
Get the image into your account's ECR — either **pull a pinned upstream tag** or **build from
upstream sources, unmodified** — then push. Keeping the image byte-for-byte upstream is what
bounds the **AGPL-3.0** boundary (we never fork or vendor it; credentials are injected at
runtime from Secrets Manager, never baked into the image).

```bash
# Variables
export AWS_REGION="us-east-1"
export ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export ECR_REPO="kiro-gateway"
export IMAGE_TAG="1.0.0"     # pin a specific version — never :latest
export UPSTREAM="ghcr.io/jwadow/kiro-gateway:${IMAGE_TAG}"

# Option A — pull the pinned upstream image (unmodified)
docker pull "${UPSTREAM}"

# Option B — build from upstream sources, UNMODIFIED (do not patch the Dockerfile/source)
#   git clone <upstream kiro-gateway repo> && cd kiro-gateway && git checkout <pinned ref>
#   docker build -t "${UPSTREAM}" .

# 1. Create the ECR repo once (idempotent — ignore "already exists")
aws ecr create-repository --repository-name "${ECR_REPO}" --region "${AWS_REGION}" \
  --image-scanning-configuration scanOnPush=true || true

# 2. Log in to ECR
aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin \
      "${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

# 3. Tag for ECR and push
export ECR_IMAGE="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}:${IMAGE_TAG}"
docker tag "${UPSTREAM}" "${ECR_IMAGE}"
docker push "${ECR_IMAGE}"

# 4. Wire the pushed image into Terraform
#    gateway_image = "<ECR_IMAGE>"   (terraform.tfvars)  OR  GATEWAY_IMAGE=... in deploy.env
echo "${ECR_IMAGE}"
```

> ⚠️ **AGPL boundary:** deploy the image **unmodified**. Do not bake credentials, config, or
> patches into it — the gateway reads `PROXY_API_KEY` and Kiro SSO credentials from Secrets
> Manager at runtime (injected by the ECS task definition's `secrets` block).

### 6.2 Load Kiro credentials into Secrets Manager

The gateway authenticates to Kiro with your **Kiro CLI / IDE login** — there is no file you
author by hand. `scripts/kiro-creds-to-secret.sh` reads your local `kiro-cli` SQLite DB,
extracts only the auth material, reshapes it into the gateway's JSON credentials format, and
pushes it to the Secrets Manager container Terraform created.

What it extracts and why:
- `accessToken` / `refreshToken` / `expiresAt` / `region` — from `auth_kv` (`kirocli:odic:token`).
- `clientId` / `clientSecret` — from `auth_kv` (`kirocli:odic:device-registration`) → OIDC path.
- `profileArn` — from the `state` table (`api.codewhisperer.profile`). **Required**: the Kiro
  API rejects requests without it (`400 profileArn is required`), even on the OIDC path. The
  script discovers it automatically; nothing to set by hand.

```bash
# Prereqs on the operator machine: logged-in kiro-cli, plus sqlite3, jq, aws CLI.
# Push straight to the gateway secret (container must already exist — Terraform creates it):
scripts/kiro-creds-to-secret.sh -p slack-devops-agent -r us-east-1
#   -p <name_prefix>  -> secret id "<prefix>/inference/kiro-sso-credentials"
#   -s <secret-id>    -> explicit secret id/ARN instead of -p
#   -o creds.json     -> write the JSON to a local 0600 file (no AWS call) to inspect first
```

How it reaches the container (no image change, AGPL-safe): the gateway task definition runs a
tiny **init container** that writes the secret JSON to a task-local shared volume at
`/creds/kiro-auth-token.json`; the unmodified gateway reads it via `KIRO_CREDS_FILE`. The
secret value never lives in the image and never appears in the gateway container's environment.

> **Token refresh / rotation:** the gateway refreshes the access token from the `refreshToken`
> automatically; the refreshed value only persists to the ephemeral volume. If the
> `refreshToken` itself is ever invalidated, re-run `kiro-creds-to-secret.sh` to update the
> secret and redeploy the service. The whole apply-then-load flow is automated by
> `scripts/deploy.sh --apply --load-kiro-creds`.

> **Port note:** the gateway listens on **8000** (the `gateway` module's `container_port`, ALB
> target group, and `/health` check are aligned to 8000).

---

## 7. Post-deploy verification

1. Update the Slack app Request URL with the API Gateway output; confirm URL
   verification succeeds.
2. `@mention` the bot in an allowlisted channel with a simple question — expect an
   ack < 3s, a "still working…" heartbeat ~15s, then a cited answer.
3. React 👍 / 👎 on an answer — confirm the feedback is recorded.
4. `@mention` from a **non-allowlisted** channel — expect the configured
   not-designated reply.
5. Paste a fake AWS key — expect a hard refuse naming the pattern class (no forwarding).
6. Check CloudWatch logs/metrics carry the correlation-id and no secrets.

---

## 8. Monthly cost estimate (AWS, us-east-1)

> **Source & caveat:** Unit prices below were grounded via the AWS Knowledge MCP
> server (Bedrock, Fargate, VPC/NAT, API Gateway pricing pages). They are **planning
> estimates**, region `us-east-1`, list price, taxes excluded. For an authoritative,
> region-exact quote use the **[AWS Pricing Calculator](https://calculator.aws/)**.
> Your **Kiro subscription** is billed separately by Kiro and is **not** an AWS charge.

### Key cost insight

Because **Kiro is the primary inference backend** (billed via your flat Kiro
subscription, not per-token on AWS) and the **`aws-knowledge-mcp-server` is a free
hosted endpoint**, the AWS bill is **dominated by always-on infrastructure** and is
**largely independent of question volume**. Per-token Bedrock cost applies **only on
failover**.

### Fixed / always-on costs (the bulk of the bill)

| Component | Basis (us-east-1 list) | ~Monthly (1 AZ) | ~Monthly (2 AZ / HA) |
|---|---|---|---|
| ECS Fargate — kiro-gateway, 2 tasks @ 0.5 vCPU / 1 GB, 24×7 | ~$0.04048 / vCPU-hr + ~$0.004445 / GB-hr | ~$36 | ~$36 (2 tasks already span AZs) |
| NAT Gateway | $0.045 / hr + $0.045 / GB processed | ~$33 + data | ~$66 + data |
| Internal ALB (fronting the gateway) | ~$0.0225 / hr + LCU | ~$18–22 | ~$18–22 |
| VPC interface endpoints (SQS, Secrets Mgr, Logs, ECR×2 — **Bedrock off by default**) | ~$0.01 / hr per endpoint per AZ | ~$37 | ~$73 |
| Secrets Manager (~5 secrets) | $0.40 / secret / mo | ~$2 | ~$2 |
| CloudWatch (logs + metrics + dashboard + alarms) | $0.50/GB ingest, $0.30/metric | ~$5–15 | ~$5–15 |
| DynamoDB on-demand + PITR (3 tables, low traffic) | $1.25/M writes, $0.25/M reads | ~$1–3 | ~$1–3 |
| KMS customer-managed key(s) | $1 / key / mo | ~$1–2 | ~$1–2 |
| **Fixed subtotal** | | **~$135–150** | **~$200–220** |

> **Biggest levers:** the NAT Gateway and VPC interface endpoints together are ~half
> the bill. The **Bedrock interface endpoint is off by default**
> (`create_bedrock_endpoint = false`, failover egresses via NAT), which already trims the
> set from 6 to 5 endpoints (~$7/AZ). If you don't need private egress you can drop to a
> single NAT AZ, or trade interface endpoints against NAT routing (each toggle is
> independent). Dropping the gateway to 1 task removes HA
> and saves ~$18/mo. Fargate Spot (−70%) is **not** recommended for the always-on
> primary inference path.

### Variable costs (per question)

| Component | Per question | At 1,000 q/mo | At 5,000 q/mo |
|---|---|---|---|
| Inference — **Kiro primary** | $0 incremental on AWS (Kiro subscription) | $0 | $0 |
| Inference — **if forced to Bedrock failover** (Claude Sonnet ~$3/M in, $15/M out; ~15k in + 3k out/question ≈ $0.09) | ~$0.09 | ~$90 | ~$450 |
| AWS Knowledge MCP grounding calls | free hosted endpoint | $0 | $0 |
| Lambda + API GW (HTTP $1/M) + DynamoDB + SQS | < $0.002 | ~$1–2 | ~$5–10 |
| NAT data processing + HTTPS egress | ~$0.045/GB | ~$1–5 | ~$3–15 |

### Bottom line

| Scenario | Est. monthly AWS cost |
|---|---|
| Normal operation (Kiro primary), 1 AZ | **~$140–170 / month** |
| Normal operation (Kiro primary), 2 AZ / HA | **~$205–240 / month** |
| Sustained Bedrock failover, 1,000 q/mo | add **~$90 / month** |
| Sustained Bedrock failover, 5,000 q/mo | add **~$450 / month** |

Plus your existing **Kiro subscription** (flat, billed by Kiro — unchanged by this deployment).

### Assumptions

- Single-workspace internal tool, business-hours usage, moderate volume (≤ the
  NFR-13 default of 500 questions/24h soft budget).
- Gateway sized at 2 × (0.5 vCPU / 1 GB); resize via Terraform vars if load grows
  (autoscaling 2→4 is configured on CPU).
- ~15k input + ~3k output tokens per question aggregated across the agent loop — a
  rough average; architecture-review questions with large thread context cost more.
- Prices are list, `us-east-1`, excluding taxes and any free-tier credits.

---

## 9. Operational notes

- **Scaling:** worker scales on SQS depth (reserved concurrency 15, max 12 in-flight);
  gateway autoscales 2→4 tasks on CPU.
- **Recovery:** the EventBridge reaper reclaims jobs whose lease is stale > 90s.
- **Failover to Bedrock:** flip the CMP-003 provider config; no code change. Watch the
  per-token cost above while on Bedrock.
- **Observability:** every log line carries the `correlation-id`; alarms fire on the
  NFR latency/availability/breaker signals.
- **Secrets rotation:** rotate Slack tokens and `PROXY_API_KEY` in Secrets Manager;
  the runtime reads them at invocation.


---

## 10. Detailed cost breakdown (line item, us-east-1)

All rates are **list price, `us-east-1`, taxes excluded**, 730 hours/month.
**Source legend:** `[MCP]` = confirmed via AWS Knowledge MCP; `[list]` = standard AWS
public list price (the exact figure sits behind a UI tab the MCP can't render — verify on
the linked pricing page or the [AWS Pricing Calculator](https://calculator.aws/)).

### 10.1 Per-unit rates used

| Service | Rate | Source |
|---|---|---|
| Fargate Linux/x86 vCPU | $0.04048 / vCPU-hour | [list] |
| Fargate Linux/x86 memory | $0.004445 / GB-hour | [list] |
| NAT Gateway | $0.045 / hour + $0.045 / GB processed | [MCP] |
| Application Load Balancer | $0.0225 / hour + $0.008 / LCU-hour | [MCP rate page + list] |
| VPC interface endpoint (PrivateLink) | $0.01 / hour per AZ + $0.01 / GB | [list] |
| VPC **gateway** endpoint (DynamoDB/S3) | free | [MCP] |
| API Gateway HTTP API | $1.00 / million requests | [MCP] |
| Lambda requests | $0.20 / million | [list] |
| Lambda compute | $0.0000166667 / GB-second | [list] |
| DynamoDB on-demand write | $1.25 / million WRU | [list] |
| DynamoDB on-demand read | $0.25 / million RRU | [list] |
| DynamoDB storage / PITR | $0.25 / $0.20 per GB-month | [list] |
| SQS standard | $0.40 / million requests (first 1M free) | [list] |
| Secrets Manager | $0.40 / secret-month + $0.05 / 10k calls | [list] |
| CloudWatch logs ingest | $0.50 / GB | [list] |
| CloudWatch custom metric | $0.30 / metric-month | [list] |
| CloudWatch dashboard / alarm | $3 / dashboard · $0.10 / alarm | [list] |
| KMS customer-managed key | $1 / key-month + $0.03 / 10k requests | [list] |
| Bedrock Claude Sonnet 4.5 | ~$3 / 1M input · ~$15 / 1M output | [list — **verify**] |
| Bedrock Claude Haiku 4.5 | ~$1 / 1M input · ~$5 / 1M output | [list — **verify**] |
| AWS Knowledge MCP server | free hosted endpoint | [MCP] |
| Kiro inference (primary) | flat **Kiro subscription** (not an AWS charge) | external |

### 10.2 Fixed monthly costs — full arithmetic

| Line | Calculation | 1 AZ | 2 AZ (HA) |
|---|---|---:|---:|
| Fargate gateway — 2 × (0.5 vCPU / 1 GB), 24×7 | vCPU: 2×0.5×730×$0.04048 = $29.55 · mem: 2×1×730×$0.004445 = $6.49 | **$36.04** | **$36.04** |
| NAT Gateway (hourly) | 1×730×$0.045 / 2×730×$0.045 | $32.85 | $65.70 |
| NAT data processing (~10–20 GB) | 10×$0.045 / 20×$0.045 | $0.45 | $0.90 |
| Internal ALB | $0.0225×730 = $16.43 + ~$3 LCU | $19.43 | $21.43 |
| VPC interface endpoints (5 by default: SQS, Secrets, Logs, ECR-api, ECR-dkr — Bedrock off) | 5×$0.01×730×(AZ) | $36.50 | $73.00 |
| Secrets Manager (5 secrets) | 5×$0.40 + calls | $2.05 | $2.05 |
| CloudWatch (logs ~5 GB + ~15 metrics + 1 dash + ~10 alarms) | $2.50 + $4.50 + $3 + $1 | $11.00 | $13.00 |
| DynamoDB (3 tables, low traffic, PITR) | ops < $1 + storage/PITR | $2.00 | $2.00 |
| KMS (1 CMK) | $1 + requests | $1.50 | $1.50 |
| **Fixed subtotal** | | **≈ $142 / mo** | **≈ $216 / mo** |

> **NAT + interface endpoints = ~$70 (1 AZ) / ~$139 (2 AZ)** — over half the fixed bill.
> Biggest optimization target (see §10.5). Figures assume the **Bedrock endpoint off by
> default**; enabling it adds ~$7.30/AZ/mo (~$7 at 1 AZ, ~$15 at 2 AZ).

### 10.3 Variable costs — full arithmetic

Assumed per question, aggregated across the agent loop: **~15k input + ~3k output tokens**,
~10 DynamoDB ops, ~2–3 SQS/API GW requests, worker ~30s @ 512 MB.

| Line | Per question | 1,000 q/mo | 5,000 q/mo |
|---|---:|---:|---:|
| Lambda (worker 0.5 GB × 30 s = 15 GB-s × $0.0000166667 + reqs) | ~$0.00027 | $0.27 | $1.35 |
| API Gateway HTTP (≈2 req) | ~$0.000002 | $0.002 | $0.01 |
| DynamoDB (~10 ops) | ~$0.00002 | $0.02 | $0.10 |
| SQS (~3 req) | ~$0.0000012 | ~$0 | $0.01 |
| NAT data (MCP + inference egress, ~0.05 GB/q) | ~$0.00225 | $2.25 | $11.25 |
| **AWS infra variable subtotal** | **~$0.003** | **≈ $3 / mo** | **≈ $13 / mo** |
| Inference — **Kiro primary** | $0 (subscription) | **$0** | **$0** |
| Inference — **Bedrock Sonnet failover** (15k×$3/M + 3k×$15/M = $0.09) | $0.09 | +$90 | +$450 |
| Inference — **Bedrock Haiku failover** (15k×$1/M + 3k×$5/M = $0.03) | $0.03 | +$30 | +$150 |

### 10.4 Scenario totals

| Scenario | Fixed | Variable | **Total AWS / month** |
|---|---:|---:|---:|
| Kiro primary, 1 AZ, 1,000 q/mo | $142 | $3 | **≈ $145** |
| Kiro primary, 2 AZ HA, 1,000 q/mo | $216 | $3 | **≈ $219** |
| Kiro primary, 2 AZ HA, 5,000 q/mo | $216 | $13 | **≈ $229** |
| 2 AZ HA + **all** on Bedrock Sonnet, 1,000 q/mo | $216 | $93 | **≈ $309** |
| 2 AZ HA + **all** on Bedrock Sonnet, 5,000 q/mo | $216 | $463 | **≈ $679** |
| 2 AZ HA + **all** on Bedrock Haiku, 5,000 q/mo | $216 | $163 | **≈ $379** |

> Fixed costs assume the **Bedrock interface endpoint is off** (the default) — Bedrock failover
> traffic egresses via NAT (counted in the variable NAT-data line). If you run sustained
> Bedrock failover you may enable `create_bedrock_endpoint` for private egress (+~$7.30/AZ/mo).

> Add your flat **Kiro subscription** (billed by Kiro, unchanged by this deployment).
> Bedrock figures apply **only while failed over** — in normal Kiro-primary operation the
> variable cost is just the ~$3–13/mo of AWS plumbing.

### 10.5 Cost-optimization levers

1. **Single NAT AZ** instead of two → saves ~$33/mo (accepts NAT as an AZ SPOF for egress).
2. **Trade interface endpoints for NAT routing** — each interface endpoint is independently
   toggleable (`create_*_endpoint`). The Bedrock endpoint is already off by default (5 active);
   if you drop the remaining PrivateLink endpoints and route that traffic through NAT, you save
   ~$37 (1 AZ) / ~$73 (2 AZ) in endpoint
   hours but add NAT data-processing $0.045/GB. Net-positive at this low data volume.
3. **Right-size the gateway** — 2 × (0.25 vCPU / 0.5 GB) halves Fargate to ~$18/mo if the
   kiro-gateway runs comfortably smaller (load-test first).
4. **One gateway task** (no Multi-AZ HA) → −$18/mo; not recommended for the primary path.
5. **Prefer Haiku over Sonnet on the Bedrock failover path** → ~3× cheaper per question.
6. **Cap thread-context tokens** (NFR-14 budget) to keep input tokens — and any Bedrock
   spend — predictable.

> These are **planning estimates**. For a binding, region-exact quote, model the exact
> instance/endpoint set in the **[AWS Pricing Calculator](https://calculator.aws/)**.
