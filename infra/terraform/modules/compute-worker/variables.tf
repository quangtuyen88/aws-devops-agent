variable "name_prefix" {
  type        = string
  description = "Resource name prefix."
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Tags applied to all resources."
}

variable "runtime" {
  type        = string
  description = "Lambda runtime."
}

variable "artifact_s3_bucket" {
  type        = string
  description = "S3 bucket of the Lambda deployment package."
}

variable "artifact_s3_key" {
  type        = string
  description = "S3 key of the Lambda deployment package."
}

variable "role_arn" {
  type        = string
  description = "worker-lambda-role ARN."
}

variable "timeout_seconds" {
  type        = number
  description = "Worker Lambda hard timeout (>= budget)."
}

variable "reserved_concurrency" {
  type        = number
  description = "Reserved concurrency (NFR-10 headroom)."
}

variable "event_source_max_concurrency" {
  type        = number
  description = "SQS event-source maximum concurrency."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnets for the worker ENIs."
}

variable "worker_sg_id" {
  type        = string
  description = "Worker security group ID."
}

variable "work_queue_arn" {
  type        = string
  description = "C-1 work queue ARN (event source)."
}

variable "table_processing_job" {
  type        = string
  description = "ProcessingJob table name."
}

variable "table_operational" {
  type        = string
  description = "OperationalData table name."
}

variable "table_config" {
  type        = string
  description = "Config table name."
}

variable "answer_ts_index" {
  type        = string
  description = "Answer-ts GSI name."
}

variable "gateway_base_url" {
  type        = string
  description = "Internal kiro-gateway base URL."
}

variable "inference_backend" {
  type        = string
  description = "Selected inference backend (kiro|bedrock)."
}

variable "mcp_base_url" {
  type        = string
  description = "AWS Knowledge MCP base URL."
}

variable "request_budget_seconds" {
  type        = number
  description = "Per-request time budget (NFR-17)."
}

variable "lease_staleness_seconds" {
  type        = number
  description = "Lease staleness bound (NFR-19)."
}

variable "heartbeat_seconds" {
  type        = number
  description = "Heartbeat cadence (NFR-11)."
}

variable "max_attempts" {
  type        = number
  description = "Max attempts (BR-022)."
}
