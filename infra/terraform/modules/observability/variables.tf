variable "name_prefix" {
  type        = string
  description = "Resource name prefix."
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Tags applied to all resources."
}

variable "kms_key_arn" {
  type        = string
  description = "KMS key ARN for log group encryption."
}

variable "log_retention_days" {
  type        = number
  description = "Log group retention in days."
}

variable "aws_region" {
  type        = string
  description = "Region (for dashboard widgets)."
}

variable "intake_function" {
  type        = string
  description = "Intake Lambda function name."
}

variable "worker_function" {
  type        = string
  description = "Worker Lambda function name."
}

variable "reaper_function" {
  type        = string
  description = "Reaper Lambda function name."
}

variable "dlq_name" {
  type        = string
  description = "Dead-letter queue name (for the DLQ-depth alarm/widget)."
}
