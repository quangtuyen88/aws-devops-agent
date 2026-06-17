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
  description = "Customer-managed KMS key ARN for at-rest encryption."
  type        = string
}

variable "table_processing_job" {
  description = "ProcessingJob table name."
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
  description = "Answer-ts GSI name (F8)."
  type        = string
}
