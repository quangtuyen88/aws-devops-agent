variable "name_prefix" {
  description = "Resource name prefix."
  type        = string
}

variable "tags" {
  description = "Tags applied to all resources."
  type        = map(string)
  default     = {}
}

variable "bedrock_model_arns" {
  description = "Specific Bedrock model ARNs the worker may invoke (no wildcard)."
  type        = list(string)
  default     = []
}

variable "table_processing_job" {
  description = "ProcessingJob table name (for ARN construction)."
  type        = string
}

variable "table_operational" {
  description = "OperationalData table name."
  type        = string
}

variable "table_config" {
  description = "Config table name."
  type        = string
}

variable "answer_ts_index" {
  description = "Answer-ts GSI name."
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
