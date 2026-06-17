# Infrastructure Design — Clarification Questions (UNIT-001)

> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`) ·
> Stage: `infrastructure-design` (construction) · Unit: **UNIT-001** ·
> Owner: aidlc-systems-architect-agent · Reviewer: aidlc-architecture-reviewer-agent ·
> Autonomy: **supervised** (these questions block until answered).
>
> Scope: this stage maps the 8 components (CMP-001..008) and the two runtime roles
> (always-on intake + horizontally-scalable worker) onto concrete infrastructure, and
> resolves the 5 deferred items in the nfr-design hand-off (`nfr-spec.md §5`,
> `nfr.yaml: infrastructure_design_handoff`) plus the headline **A-1** decision —
> *how Kiro inference is invoked at deployment*. The NFR stage fixed every **policy and
> target**; these questions only choose the **concrete services/mechanisms** that must
> satisfy them. Questions are ordered by architectural impact (highest first).

---

### Q1: Which cloud provider and how many regions/accounts should UNIT-001 target?

a) **AWS, single region, single account** (one environment family: e.g. one dev + one prod account, one region)
b) AWS, single region, multi-account (separate dev/staging/prod accounts)
c) AWS, multi-region (active/active or active/passive)
d) Other (Azure / GCP / on-prem — please specify)

**Trade Offs:** The intent is AWS-centric (AWS Knowledge MCP grounding, Lambda/API GW/DynamoDB examples, repo `devops-agent-python`), so AWS is the natural fit. The bot is a **single-workspace internal tool** (A-5) with a **dependency-bounded ~99% business-hours SLO** (NFR-9, C-3) — multi-region adds cost and operational complexity (cross-region replication of the job store, queue, dedup/lease semantics) for resilience the SLO does not require. Multi-account is good hygiene but adds IaC/pipeline surface.

**Recommendation:** **(a)** AWS, single region, single account family. It matches the AWS-native ecosystem, keeps the at-most-once-completed lease semantics (NFR-19) simple, and fits the SLO. I would still parameterise the region/account in IaC so promotion to multi-account later is mechanical.

[Answer]:

---

### Q2: How is the **Kiro/inference backend (A-1)** invoked at deployment, behind the CMP-003 swap seam (API-INT-001)?

a) **Amazon Bedrock directly** (e.g. Bedrock Converse/InvokeModel) as the shipped backend; CMP-003 keeps the stable interface so a Kiro adapter can be added later
b) **Headless/programmatic Kiro endpoint** — there is a server-side Kiro API (HTTP/SDK) reachable with a service credential; CMP-003 calls it
c) **Build the seam now, defer the live backend** — implement and test CMP-003 against a mock/stub, wire the concrete backend in code-generation once the Kiro API surface is confirmed
d) Other (please specify the exact Kiro access surface)

**Trade Offs:** A-1 is flagged as the **highest-risk assumption** in the design — the whole point of the CMP-003 library seam is to let the backend swap without touching agent-core. The verbatim intent says "use our Kiro subscription for access to LLM/SLM." The open question is whether the Kiro subscription exposes a **programmatic, server-callable** surface (option b) or whether it is an IDE/interactive product without a headless API — in which case the deployable service must call **Bedrock** directly (option a), which is the AWS-native, well-documented, IAM-scoped path that cleanly satisfies NFR-9/NFR-16 (per-dependency breaker) and NFR-5 (Secrets Manager / IAM). I should not assume the Kiro API exists; per the no-assumptions policy this needs your confirmation.

**Recommendation:** **(a)** ship on **Amazon Bedrock** behind the CMP-003 seam as the concrete backend, **unless** you confirm a headless Kiro API exists and provide its surface (then b). The seam (API-INT-001) means choosing Bedrock now costs nothing later — a Kiro adapter drops in without touching CMP-002. This de-risks A-1 immediately rather than blocking on an unconfirmed Kiro API.

[Answer]:

---

### Q3: What compute runtime carries the two roles (always-on **intake** vs horizontally-scalable **worker**)?

a) **All-serverless** — intake = **API Gateway (HTTP API) + Lambda**, worker = **SQS + Lambda** (reserved/provisioned concurrency for the ≥10 NFR-10 target)
b) **All-containers** — intake + worker on **ECS Fargate** behind an ALB, worker autoscaled on SQS queue depth
c) **Hybrid** — serverless intake (API GW + Lambda for the NFR-1 3s ack) + containerised Fargate worker (long-running, ≥10 concurrency)
d) Other (EKS / EC2 / please specify)

**Trade Offs:** Intake must ack within **p95 < 3s** (NFR-1, Slack's retry window) — Lambda behind API GW does this well, with Provisioned Concurrency to bound cold starts. The worker runs a **≤30s** pipeline (NFR-2/NFR-17) with **≥10 concurrent** in-flight (NFR-10) and no head-of-line blocking — comfortably inside Lambda's 15-min limit, and SQS+Lambda gives queue-draining horizontal scale "for free." Containers (b/c) give long-lived connection reuse (helpful if MCP/inference benefit from warm pooled clients) and no cold-start tail, at the cost of always-on capacity, an ALB, and autoscaling config. The internal C-1 queue is **mandatory and durable** either way (it survives worker crash for CS-2 recovery), so SQS fits both.

**Recommendation:** **(a)** all-serverless (API GW + Lambda intake; SQS + Lambda worker). Lowest idle cost for a single-workspace tool, native fit for the queue-draining pattern and ≥10 concurrency, and the 30s budget sits well within Lambda limits. I would flag cold-start mitigation (provisioned concurrency on intake) as the one risk to watch against NFR-1.

[Answer]:

---

### Q4: What concrete **queue** and **durable datastore** back the C-1 seam, ProcessingJob lifecycle, and operational data?

a) **Amazon SQS** (queue) + **Amazon DynamoDB** (ProcessingJob de-dup/lease, usage counter, feedback, config)
b) SQS + **Aurora Serverless v2 / RDS (PostgreSQL)**
c) Other (please specify)

**Trade Offs:** The design needs: a **durable** intake→worker queue (CS-2 recovery), **at-most-once-completed** de-dup keyed on `channel-id + message-ts` (CS-3, conditional writes), a **single-winner in-progress lease** with a 90s staleness bound (NFR-19), and an **atomic-increment** usage counter (BR-019, NFR-13). DynamoDB conditional writes and atomic counters map directly onto the lease + dedup + counter semantics with single-digit-ms latency and trivial scaling; SQS (standard) gives the durable queue with visibility-timeout redelivery that aligns with the lease/recovery model (FIFO is unnecessary since dedup is enforced in the store, not the queue). A relational store (b) is heavier than this key-access workload needs.

**Recommendation:** **(a)** SQS + DynamoDB. DynamoDB's conditional writes and atomic counters are the cleanest primitives for the dedup/lease/counter rules; SQS visibility-timeout redelivery underpins NFR-19 recovery. (Subject to Q1/Q3 — if non-AWS in Q1, this changes.)

[Answer]:

---

### Q5: How is the **AWS Knowledge MCP server** (CMP-004 grounding source) reached at runtime?

a) **Hosted remote MCP endpoint** — call the managed AWS-hosted `aws-knowledge-mcp-server` over HTTPS egress (no infra to run)
b) **Self-hosted** — we run the MCP server ourselves (container/sidecar) inside our network
c) Other / not yet decided (please specify)

**Trade Offs:** This drives **network topology** and **IAM/egress**. If the MCP server is a managed AWS-hosted endpoint (a), the worker only needs **outbound HTTPS egress** (NAT/egress for Lambda-in-VPC, or no-VPC Lambda with a managed egress allowlist) and an auth credential in Secrets Manager — no server to operate, and the per-dependency circuit breaker (NFR-16) wraps a single remote call. Self-hosting (b) adds a component to deploy, patch, scale, and monitor, plus private networking — only worth it if the hosted endpoint is unavailable to us or data-residency requires it. This affects whether the worker needs to run inside a VPC at all.

**Recommendation:** **(a)** consume the **hosted remote MCP endpoint** over HTTPS, credential in Secrets Manager, wrapped by the CMP-004 client's timeout + breaker (NFR-16/NFR-17). Avoids operating an extra service for a single-workspace tool. Please confirm the endpoint is reachable from our account and what auth it requires.

[Answer]:

---

### Q6: What **IaC tool** and **deployment/observability** stack should this unit standardise on?

a) **Terraform** for IaC + **CloudWatch** (Logs/Metrics/Alarms + correlation-id structured logs) for observability
b) **AWS CDK** for IaC + CloudWatch
c) Terraform/CDK + a **managed/OTel observability backend** (e.g. CloudWatch + ADOT, or a third-party APM)
d) Other (please specify)

**Trade Offs:** NFR-20 fixes the **required signal set** (latency histograms, failure-by-cause counters, usage/degrade counters, breaker-state gauge, concurrency/recovery counters) and **correlation-id keying** — the only open choice is the **sink**. CloudWatch (EMF for structured metrics + Logs Insights) covers all of these natively on AWS with least integration effort and keeps secrets/PII out of logs (NFR-6, BR-026). On IaC: org tooling steering leans **Terraform** (fmt/validate, remote state) and treats infra execution as read-only/manual; CDK is more idiomatic if the team is Python-first and wants typed constructs. A heavier OTel/APM stack (c) is more than a single-workspace internal tool needs at launch.

**Recommendation:** **(a)** **Terraform + CloudWatch** — aligns with org IaC tooling/standards, satisfies the full NFR-20 signal set natively, and keeps the observability footprint proportional to the SLO. Secrets via **AWS Secrets Manager** with per-integration least-privilege IAM roles (NFR-5) — one scoped role per external surface (Slack, inference backend, MCP, datastore/queue).

[Answer]:

---

> **Note on artifact resolution (documented per work-method):** nfr-design did not emit
> its own `components.yaml`/`unit.md`; the richest available upstream copies are in
> `functional-design/` (NFR- and functional-enriched). This stage will copy those forward
> and expand them in place with physical infrastructure mappings, preserving all stable
> IDs (CMP-001..008, UNIT-001, NFR-*, FR-*, CS-*). No new blueprint identity is introduced.

---

## Human Answers (recorded 2026-06-17T14:13:37+08:00)

- **Q1: a** — AWS, single region, single account family (region/account parameterized in IaC).
- **Q2: BOTH backends behind CMP-003** — Kiro (primary) AND Bedrock (alternate). Kiro is
  exposed via a self-hosted **kiro-gateway** proxy (https://github.com/jwadow/kiro-gateway):
  a FastAPI service exposing an **OpenAI-compatible** `POST /v1/chat/completions` (and
  Anthropic-compatible `POST /v1/messages`) endpoint, bearer-auth via `PROXY_API_KEY`,
  serving Claude models from the Kiro subscription. CMP-003 calls the gateway over HTTPS as
  the primary backend; Bedrock (boto3 Converse) is the alternate via the same interface.
  - **Hosting implication:** kiro-gateway is a stateful long-running service (holds/refreshes
    Kiro SSO tokens) → it must be HOSTED by us as a container (see Q3), with the Kiro
    credentials + `PROXY_API_KEY` in Secrets Manager. The worker reaches it over internal HTTPS.
  - **LICENSING RISK (open, to confirm before code-generation):** kiro-gateway is AGPL-3.0;
    "network use is distribution." Running it as a service triggers source-disclosure
    obligations. Recorded as a watch-item; surface again at the code-generation gate. NOT
    silently accepted.
- **Q3: a** — Serverless bot (API Gateway + Lambda intake; SQS + Lambda worker, provisioned
  concurrency for NFR-1 cold-start) PLUS a small always-on container (ECS Fargate or App
  Runner) hosting the kiro-gateway.
- **Q4: a** — Amazon SQS (durable C-1 queue) + Amazon DynamoDB (ProcessingJob de-dup/lease via
  conditional writes, usage counter via atomic increments, feedback, config).
- **Q5: a** — Consume the hosted remote `aws-knowledge-mcp-server` over HTTPS egress; auth
  credential in Secrets Manager; wrapped by CMP-004 timeout + circuit breaker (NFR-16/17).
- **Q6: a** — Terraform IaC + CloudWatch (Logs/Metrics/Alarms, EMF, correlation-id structured
  logs) + AWS Secrets Manager; per-integration least-privilege IAM roles (Slack, Kiro-gateway,
  Bedrock, MCP, DynamoDB/SQS).
