# Root composition — wires the 9 modules (infra-spec §6). Module dependency order:
#
#   security (KMS, secrets, IAM — foundation, no deps)
#     -> data / messaging / networking (consume KMS)
#       -> gateway / compute-intake / compute-worker / recovery / observability
#
# `security` scopes its IAM policies to ARNs constructed from the name prefix, so it never
# depends on the other modules' outputs — this breaks the KMS<->ARN dependency cycle.

locals {
  common_tags = merge(
    {
      Project     = "intent-001-slack-devops-agent"
      Unit        = "UNIT-001"
      Environment = var.environment
      ManagedBy   = "terraform"
    },
    var.tags,
  )

  table_processing_job = "${var.name_prefix}-processing-job"
  table_operational    = "${var.name_prefix}-operational-data"
  table_config         = "${var.name_prefix}-config"
  answer_ts_index      = "answer-ts-index"
  work_queue_name      = "${var.name_prefix}-work-queue"
  dlq_name             = "${var.name_prefix}-work-queue-dlq"
}

# Secret values injected into the Lambda environment. NOTE: this materializes the secret values
# into Terraform state and the Lambda console env (the chosen plaintext-env wiring). Keep the
# state bucket locked down. The containers are populated out of band (scripts/load-secrets.sh);
# these data sources read the current version each apply.
data "aws_secretsmanager_secret_version" "slack_bot" {
  secret_id = module.security.secret_arns["slack_bot"]
}

data "aws_secretsmanager_secret_version" "slack_signing" {
  secret_id = module.security.secret_arns["slack_signing"]
}

data "aws_secretsmanager_secret_version" "kiro_proxy_key" {
  secret_id = module.security.secret_arns["kiro_proxy_key"]
}

module "security" {
  source = "./modules/security"

  name_prefix          = var.name_prefix
  tags                 = local.common_tags
  bedrock_model_arns   = var.bedrock_model_arns
  table_processing_job = local.table_processing_job
  table_operational    = local.table_operational
  table_config         = local.table_config
  answer_ts_index      = local.answer_ts_index
  work_queue_name      = local.work_queue_name
  dlq_name             = local.dlq_name
}

module "networking" {
  source = "./modules/networking"

  name_prefix = var.name_prefix
  tags        = local.common_tags
  aws_region  = var.aws_region
  vpc_cidr    = var.vpc_cidr
  az_count    = var.az_count

  # Existing-VPC (destroy-safe) mode — existing infra referenced by-ID via data sources only.
  use_existing_network        = var.use_existing_network
  existing_vpc_id             = var.existing_vpc_id
  existing_private_subnet_ids = var.existing_private_subnet_ids
  existing_security_group_ids = var.existing_security_group_ids
  existing_nat_gateway        = var.existing_nat_gateway

  # Per-endpoint interface VPC endpoint toggles.
  create_sqs_endpoint            = var.create_sqs_endpoint
  create_secretsmanager_endpoint = var.create_secretsmanager_endpoint
  create_logs_endpoint           = var.create_logs_endpoint
  create_ecr_api_endpoint        = var.create_ecr_api_endpoint
  create_ecr_dkr_endpoint        = var.create_ecr_dkr_endpoint
  create_bedrock_endpoint        = var.create_bedrock_endpoint
}

module "data" {
  source = "./modules/data"

  name_prefix          = var.name_prefix
  tags                 = local.common_tags
  kms_key_arn          = module.security.kms_key_arn
  table_processing_job = local.table_processing_job
  table_operational    = local.table_operational
  table_config         = local.table_config
  answer_ts_index      = local.answer_ts_index
}

module "messaging" {
  source = "./modules/messaging"

  name_prefix                = var.name_prefix
  tags                       = local.common_tags
  kms_key_arn                = module.security.kms_key_arn
  work_queue_name            = local.work_queue_name
  dlq_name                   = local.dlq_name
  visibility_timeout_seconds = var.queue_visibility_timeout_seconds
  max_receive_count          = var.max_receive_count
}

module "observability" {
  source = "./modules/observability"

  name_prefix        = var.name_prefix
  tags               = local.common_tags
  kms_key_arn        = module.security.kms_key_arn
  log_retention_days = var.log_retention_days
  aws_region         = var.aws_region
  intake_function    = "${var.name_prefix}-intake"
  worker_function    = "${var.name_prefix}-worker"
  reaper_function    = "${var.name_prefix}-reaper"
  dlq_name           = local.dlq_name
}

module "gateway" {
  source = "./modules/gateway"

  name_prefix              = var.name_prefix
  tags                     = local.common_tags
  vpc_id                   = module.networking.vpc_id
  private_subnet_ids       = module.networking.private_subnet_ids
  worker_sg_id             = module.networking.worker_sg_id
  image                    = var.gateway_image
  desired_count            = var.gateway_desired_count
  autoscale_min_capacity   = var.gateway_autoscale_min_capacity
  autoscale_max_capacity   = var.gateway_autoscale_max_capacity
  autoscale_cpu_target     = var.gateway_autoscale_cpu_target
  certificate_arn          = var.gateway_certificate_arn
  tls_enabled              = var.gateway_tls_enabled
  alb_idle_timeout_seconds = var.gateway_alb_idle_timeout_seconds
  task_role_arn            = module.security.gateway_task_role_arn
  execution_role_arn       = module.security.gateway_execution_role_arn
  proxy_key_secret         = module.security.secret_arns["kiro_proxy_key"]
  sso_secret               = module.security.secret_arns["kiro_sso"]
  log_retention_days       = var.log_retention_days
  kms_key_arn              = module.security.kms_key_arn

  # Existing-ALB (destroy-safe) mode — add a listener rule to a borrowed ALB instead of one.
  use_existing_alb          = var.existing_alb
  existing_alb_listener_arn = var.existing_alb_listener_arn
}

module "compute_intake" {
  source = "./modules/compute-intake"

  name_prefix             = var.name_prefix
  tags                    = local.common_tags
  runtime                 = var.lambda_runtime
  artifact_s3_bucket      = var.lambda_artifact_s3_bucket
  artifact_s3_key         = var.lambda_artifact_s3_key
  role_arn                = module.security.intake_role_arn
  provisioned_concurrency = var.intake_provisioned_concurrency
  work_queue_url          = module.messaging.work_queue_url
  table_processing_job    = local.table_processing_job
  table_operational       = local.table_operational
  table_config            = local.table_config
  answer_ts_index         = local.answer_ts_index
  heartbeat_seconds       = var.heartbeat_seconds
  lease_staleness_seconds = var.lease_staleness_seconds
  request_budget_seconds  = var.request_time_budget_seconds
  max_attempts            = var.max_receive_count
  slack_signing_secret    = data.aws_secretsmanager_secret_version.slack_signing.secret_string
  slack_bot_token         = data.aws_secretsmanager_secret_version.slack_bot.secret_string
  slack_bot_user_id       = var.slack_bot_user_id
}

module "compute_worker" {
  source = "./modules/compute-worker"

  name_prefix                  = var.name_prefix
  tags                         = local.common_tags
  runtime                      = var.lambda_runtime
  artifact_s3_bucket           = var.lambda_artifact_s3_bucket
  artifact_s3_key              = var.lambda_artifact_s3_key
  role_arn                     = module.security.worker_role_arn
  timeout_seconds              = var.worker_lambda_timeout_seconds
  reserved_concurrency         = var.worker_reserved_concurrency
  event_source_max_concurrency = var.worker_event_source_max_concurrency
  private_subnet_ids           = module.networking.private_subnet_ids
  worker_sg_id                 = module.networking.worker_sg_id
  work_queue_arn               = module.messaging.work_queue_arn
  table_processing_job         = local.table_processing_job
  table_operational            = local.table_operational
  table_config                 = local.table_config
  answer_ts_index              = local.answer_ts_index
  gateway_base_url             = "${var.gateway_tls_enabled ? "https" : "http"}://${module.gateway.alb_dns_name}"
  inference_backend            = var.inference_backend
  kiro_model                   = var.kiro_model
  kiro_timeout_seconds         = var.kiro_timeout_seconds
  mcp_base_url                 = var.mcp_base_url
  request_budget_seconds       = var.request_time_budget_seconds
  lease_staleness_seconds      = var.lease_staleness_seconds
  heartbeat_seconds            = var.heartbeat_seconds
  max_attempts                 = var.max_receive_count
  slack_bot_token              = data.aws_secretsmanager_secret_version.slack_bot.secret_string
  proxy_api_key                = data.aws_secretsmanager_secret_version.kiro_proxy_key.secret_string
  mcp_api_key                  = var.mcp_api_key
}

module "recovery" {
  source = "./modules/recovery"

  name_prefix             = var.name_prefix
  tags                    = local.common_tags
  runtime                 = var.lambda_runtime
  artifact_s3_bucket      = var.lambda_artifact_s3_bucket
  artifact_s3_key         = var.lambda_artifact_s3_key
  role_arn                = module.security.reaper_role_arn
  dlq_url                 = module.messaging.dlq_url
  table_processing_job    = local.table_processing_job
  lease_staleness_seconds = var.lease_staleness_seconds
  max_attempts            = var.max_receive_count
  slack_bot_token         = data.aws_secretsmanager_secret_version.slack_bot.secret_string
}
