variable "name_prefix" {
  type        = string
  description = "Resource name prefix."
}

variable "tags" {
  type        = map(string)
  default     = {}
  description = "Tags applied to all resources."
}

variable "vpc_id" {
  type        = string
  description = "VPC ID."
}

variable "private_subnet_ids" {
  type        = list(string)
  description = "Private subnets for the ALB and Fargate tasks."
}

variable "worker_sg_id" {
  type        = string
  description = "Worker SG permitted to reach the internal ALB."
}

variable "image" {
  type        = string
  description = "Unmodified upstream kiro-gateway image (AGPL boundary)."
}

variable "desired_count" {
  type        = number
  description = "Fargate baseline task count (Multi-AZ, F4)."
}

variable "autoscale_min_capacity" {
  type        = number
  default     = 2
  description = "Application Auto Scaling minimum task count (infra-spec §2.3 baseline, F4)."
}

variable "autoscale_max_capacity" {
  type        = number
  default     = 4
  description = "Application Auto Scaling maximum task count (infra-spec §2.3 ceiling 2->4, F4)."
}

variable "autoscale_cpu_target" {
  type        = number
  default     = 70
  description = "Target-tracking ECSServiceAverageCPUUtilization percentage that drives scale-out/in."
}

variable "certificate_arn" {
  type        = string
  default     = ""
  description = "ACM certificate ARN for the internal ALB TLS listener (unused in existing-ALB mode — the borrowed listener carries its own cert)."
}

variable "tls_enabled" {
  type        = bool
  default     = false
  description = "Create a 443/HTTPS listener (requires certificate_arn). When false, create a plaintext 80/HTTP listener for the internal worker→ALB hop (no cert needed)."
}

variable "alb_idle_timeout_seconds" {
  type        = number
  default     = 80
  description = "ALB idle timeout. MUST be >= the kiro gateway HTTP client timeout (KIRO_TIMEOUT_SECONDS) so the ALB does not 504 a slow-but-valid inference before the app timeout fires."
}

# --- Existing-ALB (destroy-safe) mode ---

variable "use_existing_alb" {
  type        = bool
  default     = false
  description = "Add a listener rule to an existing ALB listener (by-ARN) instead of creating an ALB. Existing ALB is referenced via data sources only and never managed."
}

variable "existing_alb_listener_arn" {
  type        = string
  default     = ""
  description = "ARN of the existing ALB HTTPS listener to attach a forwarding rule to (when use_existing_alb = true)."
}

variable "existing_alb_listener_rule_priority" {
  type        = number
  default     = 100
  description = "Priority of the listener rule added to the existing ALB listener."
}

variable "task_role_arn" {
  type        = string
  description = "kiro-gateway task role ARN (no data-plane perms)."
}

variable "execution_role_arn" {
  type        = string
  description = "ECS execution role ARN (image pull + log + secret injection)."
}

variable "proxy_key_secret" {
  type        = string
  description = "Secrets Manager ARN of the gateway PROXY_API_KEY."
}

variable "sso_secret" {
  type        = string
  description = "Secrets Manager ARN of the Kiro OIDC credentials JSON (accessToken/refreshToken/expiresAt/region/clientId/clientSecret). Injected into the init container and written to KIRO_CREDS_FILE."
}

variable "creds_init_image" {
  type        = string
  default     = "public.ecr.aws/docker/library/busybox:1.36.1"
  description = "Stock image for the init container that materializes the Kiro creds JSON to the shared volume (pinned tag, not :latest)."
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention."
}

variable "kms_key_arn" {
  type        = string
  description = "KMS key ARN for the gateway log group."
}
