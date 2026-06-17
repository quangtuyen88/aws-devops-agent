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
  description = "reaper-lambda-role ARN."
}

variable "dlq_url" {
  type        = string
  description = "Dead-letter queue URL to drain."
}

variable "table_processing_job" {
  type        = string
  description = "ProcessingJob table name."
}

variable "lease_staleness_seconds" {
  type        = number
  description = "Lease staleness bound (NFR-19)."
}

variable "max_attempts" {
  type        = number
  description = "Max attempts (BR-022)."
}

variable "schedule_expression" {
  type        = string
  default     = "rate(1 minute)"
  description = "EventBridge Scheduler cadence for the recovery scan."
}
