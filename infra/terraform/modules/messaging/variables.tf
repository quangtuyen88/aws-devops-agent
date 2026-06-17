variable "name_prefix" {
  description = "Resource name prefix."
  type        = string
}

variable "tags" {
  description = "Tags applied to all resources."
  type        = map(string)
  default     = {}
}

variable "kms_key_arn" {
  description = "Customer-managed KMS key ARN for SQS SSE."
  type        = string
}

variable "work_queue_name" {
  description = "Work queue name."
  type        = string
}

variable "dlq_name" {
  description = "Dead-letter queue name."
  type        = string
}

variable "visibility_timeout_seconds" {
  description = "SQS visibility timeout (== lease staleness, infra-spec §2.4)."
  type        = number
}

variable "max_receive_count" {
  description = "Receives before redrive to DLQ (== max attempts, BR-022)."
  type        = number
}
