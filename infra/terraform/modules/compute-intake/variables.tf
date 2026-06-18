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
  description = "intake-lambda-role ARN."
}

variable "provisioned_concurrency" {
  type        = number
  description = "Provisioned concurrency on the live alias (0 disables)."
}

variable "work_queue_url" {
  type        = string
  description = "C-1 work queue URL."
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

variable "heartbeat_seconds" {
  type        = number
  description = "Heartbeat cadence (NFR-11)."
}

variable "lease_staleness_seconds" {
  type        = number
  description = "Lease staleness bound (NFR-19)."
}

variable "request_budget_seconds" {
  type        = number
  description = "Per-request time budget (NFR-17)."
}

variable "max_attempts" {
  type        = number
  description = "Max attempts (BR-022)."
}

variable "slack_signing_secret" {
  type        = string
  sensitive   = true
  description = "Slack signing secret value (request signature verification)."
}

variable "slack_bot_token" {
  type        = string
  sensitive   = true
  description = "Slack bot OAuth token value (posts the ack)."
}

variable "slack_bot_user_id" {
  type        = string
  default     = ""
  description = "Slack bot user id (self-mention suppression)."
}
