# Root input variables — region/account parameterised for mechanical multi-account promotion.

variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix for all resource names (keeps a deploy self-contained per account/env)."
  type        = string
  default     = "slack-devops-agent"
}

variable "environment" {
  description = "Deployment environment (e.g. dev, staging, prod)."
  type        = string
  default     = "dev"
}

variable "tags" {
  description = "Extra tags merged onto every resource."
  type        = map(string)
  default     = {}
}

# --- Networking (infra-spec §3) ---

variable "vpc_cidr" {
  description = "CIDR block for the worker VPC."
  type        = string
  default     = "10.40.0.0/16"
}

variable "az_count" {
  description = "Number of AZs to spread private/public subnets across (Multi-AZ, F4)."
  type        = number
  default     = 2
}

# --- Lambda artifact (one image/zip for intake+worker+reaper, infra-spec §6 two-role deploy) ---

variable "lambda_artifact_s3_bucket" {
  description = "S3 bucket holding the built UNIT-001 Lambda deployment package."
  type        = string
  default     = ""
}

variable "lambda_artifact_s3_key" {
  description = "S3 key of the built UNIT-001 Lambda deployment package (zip)."
  type        = string
  default     = "slack-devops-agent/unit-001.zip"
}

variable "lambda_runtime" {
  description = "Lambda runtime (matches pyproject Python 3.12)."
  type        = string
  default     = "python3.12"
}

# --- Timing invariant (infra-spec §2.4 — MUST move in lock-step) ---

variable "request_time_budget_seconds" {
  description = "App soft per-request budget (NFR-17)."
  type        = number
  default     = 30
}

variable "worker_lambda_timeout_seconds" {
  description = "Worker Lambda hard timeout (>= budget; infra-spec §2.4)."
  type        = number
  default     = 45
}

variable "queue_visibility_timeout_seconds" {
  description = "SQS visibility timeout (== lease staleness; infra-spec §2.4)."
  type        = number
  default     = 90
}

variable "lease_staleness_seconds" {
  description = "Lease staleness bound (NFR-19, inclusive >= reclaim)."
  type        = number
  default     = 90
}

variable "max_receive_count" {
  description = "SQS maxReceiveCount before DLQ (== max attempts, BR-022)."
  type        = number
  default     = 3
}

variable "heartbeat_seconds" {
  description = "Heartbeat cadence (NFR-11)."
  type        = number
  default     = 15
}

# --- Scaling (infra-spec §2.2) ---

variable "worker_reserved_concurrency" {
  description = "Worker Lambda reserved concurrency (NFR-10 headroom)."
  type        = number
  default     = 15
}

variable "worker_event_source_max_concurrency" {
  description = "SQS event-source maximum concurrency (caps fan-out; NFR-10)."
  type        = number
  default     = 12
}

variable "intake_provisioned_concurrency" {
  description = "Intake Lambda provisioned concurrency (bounds NFR-1 cold-start tail)."
  type        = number
  default     = 2
}

# --- Inference gateway (infra-spec §2.3) ---

variable "gateway_image" {
  description = "Unmodified upstream kiro-gateway container image (AGPL boundary, §0)."
  type        = string
  default     = ""
}

variable "gateway_desired_count" {
  description = "kiro-gateway Fargate baseline task count (Multi-AZ baseline, F4)."
  type        = number
  default     = 2
}

variable "gateway_autoscale_min_capacity" {
  description = "kiro-gateway Application Auto Scaling minimum task count (infra-spec §2.3 baseline, F4)."
  type        = number
  default     = 2
}

variable "gateway_autoscale_max_capacity" {
  description = "kiro-gateway Application Auto Scaling maximum task count (infra-spec §2.3 ceiling 2->4, F4)."
  type        = number
  default     = 4
}

variable "gateway_autoscale_cpu_target" {
  description = "kiro-gateway target-tracking ECSServiceAverageCPUUtilization percentage."
  type        = number
  default     = 70
}

variable "gateway_certificate_arn" {
  description = "ACM cert ARN for the internal ALB TLS listener (NFR-5)."
  type        = string
  default     = ""
}

# --- Bedrock alternate (infra-spec §4.2 least-privilege) ---

variable "bedrock_model_arns" {
  description = "Specific Bedrock model ARNs the worker may invoke (no wildcard)."
  type        = list(string)
  default     = []
}

# --- Non-secret runtime config (secrets injected from Secrets Manager at runtime) ---

variable "inference_backend" {
  description = "Selected inference backend: kiro (primary) or bedrock (alternate)."
  type        = string
  default     = "kiro"
}

variable "mcp_base_url" {
  description = "AWS Knowledge MCP server base URL."
  type        = string
  default     = ""
}

variable "log_retention_days" {
  description = "CloudWatch log group retention."
  type        = number
  default     = 30
}

# --- Existing-network / existing-ALB (destroy-safe) mode (infra-spec §3) ---
#
# DESTROY-SAFETY GUARANTEE: when use_existing_network / existing_alb are true, the pre-existing
# VPC, subnets, security groups, NAT, and ALB are referenced through Terraform DATA SOURCES /
# by-ID only — never as managed `resource` blocks. `terraform destroy` therefore removes only
# app-created resources (Lambdas, SQS, DynamoDB, ECS service/task, the endpoints we created,
# IAM, secrets, and any listener rule we added) and can NEVER delete the borrowed VPC, subnets,
# SG, NAT, or ALB. With the defaults (false) the stack creates and owns the VPC/NAT/ALB.

variable "use_existing_network" {
  description = "Consume an existing VPC/subnets/SG (data sources only) instead of creating them. Default false (create the VPC/NAT)."
  type        = bool
  default     = false
}

variable "existing_vpc_id" {
  description = "ID of the pre-existing VPC (when use_existing_network = true)."
  type        = string
  default     = ""
}

variable "existing_private_subnet_ids" {
  description = "IDs of the pre-existing private subnets for in-VPC compute (when use_existing_network = true)."
  type        = list(string)
  default     = []
}

variable "existing_security_group_ids" {
  description = "IDs of the pre-existing security group(s) for in-VPC compute (when use_existing_network = true)."
  type        = list(string)
  default     = []
}

variable "existing_nat_gateway" {
  description = "Reuse the existing VPC's NAT (skip creating one). Default false."
  type        = bool
  default     = false
}

variable "existing_alb" {
  description = "Add a listener rule to an existing ALB (data sources / by-ARN) instead of creating one. Default false."
  type        = bool
  default     = false
}

variable "existing_alb_listener_arn" {
  description = "ARN of the existing ALB HTTPS listener to attach a forwarding rule to (when existing_alb = true)."
  type        = string
  default     = ""
}

# --- Per-endpoint interface VPC endpoint toggles (count = var.X ? 1 : 0) ---
# DynamoDB/S3 remain free gateway endpoints (always created, not toggled).

variable "create_sqs_endpoint" {
  description = "Create the SQS interface VPC endpoint."
  type        = bool
  default     = true
}

variable "create_secretsmanager_endpoint" {
  description = "Create the Secrets Manager interface VPC endpoint."
  type        = bool
  default     = true
}

variable "create_logs_endpoint" {
  description = "Create the CloudWatch Logs interface VPC endpoint."
  type        = bool
  default     = true
}

variable "create_ecr_api_endpoint" {
  description = "Create the ECR API interface VPC endpoint."
  type        = bool
  default     = true
}

variable "create_ecr_dkr_endpoint" {
  description = "Create the ECR Docker (dkr) interface VPC endpoint."
  type        = bool
  default     = true
}

variable "create_bedrock_endpoint" {
  description = "Create the Bedrock runtime interface VPC endpoint. Default FALSE — Bedrock failover egresses via NAT unless compliance requires PrivateLink."
  type        = bool
  default     = false
}
