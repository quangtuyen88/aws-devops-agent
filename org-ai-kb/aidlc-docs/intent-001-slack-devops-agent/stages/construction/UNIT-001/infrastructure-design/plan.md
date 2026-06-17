# Infrastructure Design — Plan (UNIT-001)

> Intent: **Slack DevOps Agent Bot** (`intent-001-slack-devops-agent`) ·
> Stage: `infrastructure-design` (construction) · Unit: **UNIT-001** ·
> Owner: aidlc-systems-architect-agent · Reviewer: aidlc-architecture-reviewer-agent ·
> Autonomy: **supervised**.

## Objective

Map the 8 logical components (CMP-001..008) and the **two-role runtime** (always-on
**intake** + horizontally-scalable **worker**, split by the internal durable C-1 queue
seam) onto concrete infrastructure services, and resolve the deferred items handed off
from nfr-design. The NFR stage fixed all **policies and targets**; this stage chooses the
**concrete services and mechanisms** that satisfy them, then verifies the mapping against
each NFR.

## Inputs (and artifact resolution)

| Input | Source used | Notes |
|---|---|---|
| NFR specification (Required) | `nfr-design/nfr-spec.md` + `nfr-design/nfr.yaml` | Source of truth for targets + `infrastructure_design_handoff` |
| `components.yaml` (Required copy-forward) | **`functional-design/components.yaml`** | **Fallback:** nfr-design emitted no `components.yaml`; richest available is functional-design's NFR+functional-enriched copy. Documented per work-method artifact-resolution rule. |
| `unit.md` (Required copy-forward) | **`functional-design/unit.md`** | Same fallback as above; preserves UNIT-001 packaging + internal module structure. |
| Functional context | `functional-design/{functional-spec,api-specification,entities,rules}.{md,yaml}` | Workflows W1..W5, API-INT-001/009 seams, ProcessingJob state machine, BR-019/021/022/027 |
| Existing-infra (RE) | n/a | reverse-engineering skipped (greenfield) — nothing to study |
| Deployment constraints | intent.md open questions + Q1..Q6 answers | hosting/runtime + Kiro-access were explicitly left open |

## Deferred items this stage must resolve (from `nfr-spec.md §5`)

1. **Exact input-token budget** (NFR-14) — finalise the number against the chosen model (default 12k fixed).
2. **Worker concurrency/instance count + scaling mechanism** (NFR-10) — pick the concrete mechanism (≥10 starting target fixed).
3. **Metrics/log sink + dashboards** (NFR-20) — pick the observability backend (signal set + correlation-id keying fixed).
4. **Secret-manager choice + per-integration IAM scopes** (NFR-5) — pick the manager + define least-privilege scopes.
5. **Concrete queue + datastore + inference backend** (A-1, Kiro/Bedrock) — pick services (dependency-bounded SLO + breaker policy fixed).

## Plan / Steps

### Phase 0 — Clarify (this step)
- [x] Read stage definition, template, conventions, and all upstream artifacts (functional-design + nfr-design)
- [x] Write `questions.md` (Q1..Q6: cloud/region, inference backend A-1, compute runtime, queue+datastore, MCP connectivity, IaC+observability+secrets)
- [x] Write `plan.md` (this file)
- [x] Set state to `clarification-asked` and hand back to orchestrator
- [x] Incorporate human answers (revise plan/decisions if answers diverge from recommendations)

### Phase 1 — Resolve deferred decisions
- [x] Record the cloud provider / region / account topology (Q1)
- [x] Resolve A-1 inference backend behind the CMP-003 seam and document how it is invoked at deployment (Q2)
- [x] Choose compute runtime for intake + worker roles, with cold-start vs NFR-1 mitigation (Q3)
- [x] Choose concrete queue + datastore and map dedup/lease/counter semantics to their primitives (Q4)
- [x] Resolve MCP server connectivity + resulting network/egress posture (Q5)
- [x] Choose IaC tool, observability sink, and secret manager (Q6); finalise the NFR-14 token budget against the chosen model

### Phase 2 — Produce `infrastructure-specification.md`
- [x] **Service Mapping** — CMP-001..008 → concrete services, with NFR-satisfied trace
- [x] **Compute** — intake vs worker compute type, sizing, scaling approach (NFR-1, NFR-2, NFR-10)
- [x] **Network Topology** — public ingress (Slack Events API HTTPS), private compute, egress to inference backend + MCP + datastore
- [x] **Security Boundaries** — per-integration IAM least-privilege (NFR-5), Secrets Manager, secret-detection pre-send gate placement (CMP-005, NFR-4), TLS in transit + encryption at rest
- [x] **Observability** — NFR-20 signal set → sink/dashboards/alarms, correlation-id keying, log hygiene (NFR-6)
- [x] **Deployment Strategy** — IaC tool, deploy method, rollback/RTO, two-role deploy, recovery scan (NFR-19)
- [x] Cross-check every NFR (1,2,5,6,7,9,10,11,12,13,14,15,16,17,19,20,21) against the chosen infrastructure; record residual risks

### Phase 3 — Copy-forward expansions (preserve stable IDs)
- [x] Copy `functional-design/components.yaml` → this stage; append physical mappings (compute, storage, network, IAM, observability, deployment) per CMP without altering IDs/boundaries
- [x] Copy `functional-design/unit.md` → this stage; append an infrastructure-design section (deployment topology, IaC module references, runtime config, operational ownership) without changing packaging decisions
- [x] Fill the template's **Copied Blueprint Expansions** table

### Phase 4 — Self-check & persist
- [x] Verify: every CMP mapped; every deferred item (1..5) resolved; every NFR traced to an infrastructure decision; no stable ID renamed; no out-of-scope work (OOS-3 never executes IaC, A-5 single workspace, A-8 no durable memory)
- [x] Register all outputs in `state/state.json` `outputs[]`
- [x] Set state to `artifact-generated`

## Outputs to be produced

| Artifact | Purpose |
|---|---|
| `infrastructure-specification.md` | Service mapping, compute, network topology, security boundaries, observability, deployment strategy (one document) |
| `components.yaml` | Copied-forward blueprint expanded with physical infrastructure mappings per CMP |
| `unit.md` | Copied-forward unit definition expanded with deployment topology, IaC refs, runtime config, operational ownership |

(`questions.md` and `plan.md` already produced this phase.)

## Risks / watch-items

- **A-1 (highest risk):** if no headless Kiro API exists, the deployable must target Bedrock behind the CMP-003 seam (Q2). Blocking decision — the seam de-risks it, but the concrete backend must be named before code-generation.
- **Cold start vs NFR-1:** serverless intake needs provisioned concurrency to hold p95<3s ack (Q3).
- **Lease vs recovery timing:** the 90s staleness bound must exceed the worker's queue visibility timeout / max runtime so a live job is never reclaimed (NFR-19) — must be set consistently across SQS visibility timeout, Lambda/worker timeout, and the lease bound.
- **Egress posture:** MCP + inference are outbound HTTPS dependencies; if compute runs in a VPC, NAT/egress cost and allowlisting apply (Q5).

---

## Phase complete — answers incorporated (2026-06-17T14:14)

Artifacts produced: `infrastructure-specification.md`, `components.yaml` (copied-forward +
`Infrastructure-Design-Refs`), `unit.md` (copied-forward + Infrastructure-Design Expansion).
Status set to `artifact-generated`.

Divergences from my recommendations (human chose, plan revised accordingly):

- **Q2** — recommended Bedrock-only behind CMP-003; human chose **both backends**, **Kiro
  primary** via a self-hosted **kiro-gateway** container + **Bedrock alternate**. This added
  an always-on ECS Fargate component (kiro-gateway) and a new **AGPL-3.0 licensing watch-item**
  carried to code-generation (not silently accepted; Bedrock-primary is the ready fallback).
- **Q3** — serverless intake+worker as recommended, **plus** the kiro-gateway container from Q2.
- **Q5** — recommended (a) hosted MCP; confirmed. Network posture finalised: worker in VPC +
  NAT for external egress (needed to privately reach kiro-gateway), interface/gateway endpoints
  for AWS services.

Deferred items resolved: NFR-14 token budget = 12,000 in / 4,000 out; NFR-10 = SQS→Lambda
batch_size=1, reserved conc. 15; NFR-20 = CloudWatch; NFR-5 = Secrets Manager + per-role IAM;
A-1 = Kiro(kiro-gateway)/Bedrock behind CMP-003; queue=SQS; datastore=DynamoDB ×3.
