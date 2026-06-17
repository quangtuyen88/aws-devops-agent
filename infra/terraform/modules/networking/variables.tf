variable "name_prefix" {
  description = "Resource name prefix."
  type        = string
}

variable "tags" {
  description = "Tags applied to all resources."
  type        = map(string)
  default     = {}
}

variable "aws_region" {
  description = "AWS region (for VPC endpoint service names)."
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR block (used only when creating the VPC)."
  type        = string
}

variable "az_count" {
  description = "Number of AZs to span (Multi-AZ baseline, F4)."
  type        = number
}

# --- Existing-network (destroy-safe) mode ---

variable "use_existing_network" {
  description = "Consume an existing VPC/subnets/SG via data sources instead of creating them. Existing infra is referenced by-ID only and never managed, so destroy can never delete it."
  type        = bool
  default     = false
}

variable "existing_vpc_id" {
  description = "ID of the pre-existing VPC to consume (when use_existing_network = true)."
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
  description = "Reuse the existing VPC's NAT (skip creating one). Default false (create a NAT when we own the network)."
  type        = bool
  default     = false
}

# --- Per-endpoint interface VPC endpoint toggles (count = var.X ? 1 : 0) ---

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
