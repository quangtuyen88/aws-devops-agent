# compute-worker — horizontally-scalable worker role (infra-spec §2.2). SQS → Lambda event
# source, batch_size=1 (no head-of-line blocking, NFR-10), reserved concurrency 15, event
# source max concurrency 12. In VPC (private subnets) for private reach to kiro-gateway.
# Timeout 45s sits above the 30s NFR-17 soft budget so the app fails gracefully first.

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

resource "aws_lambda_function" "worker" {
  function_name                  = "${var.name_prefix}-worker"
  role                           = var.role_arn
  runtime                        = var.runtime
  handler                        = "slack_devops_agent.entrypoints.lambda_worker.lambda_handler"
  timeout                        = var.timeout_seconds
  memory_size                    = 1024
  reserved_concurrent_executions = var.reserved_concurrency

  s3_bucket = var.artifact_s3_bucket
  s3_key    = var.artifact_s3_key

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [var.worker_sg_id]
  }

  environment {
    variables = {
      PROCESSING_JOB_TABLE        = var.table_processing_job
      OPERATIONAL_DATA_TABLE      = var.table_operational
      CONFIG_TABLE                = var.table_config
      ANSWER_TS_GSI               = var.answer_ts_index
      INFERENCE_BACKEND           = var.inference_backend
      KIRO_GATEWAY_BASE_URL       = var.gateway_base_url
      MCP_BASE_URL                = var.mcp_base_url
      REQUEST_TIME_BUDGET_SECONDS = tostring(var.request_budget_seconds)
      LEASE_STALENESS_SECONDS     = tostring(var.lease_staleness_seconds)
      HEARTBEAT_SECONDS           = tostring(var.heartbeat_seconds)
      MAX_ATTEMPTS                = tostring(var.max_attempts)
    }
  }

  tags = var.tags
}

# SQS event source: one job per invocation; cap fan-out at the NFR-10 maximum concurrency.
resource "aws_lambda_event_source_mapping" "work" {
  event_source_arn = var.work_queue_arn
  function_name    = aws_lambda_function.worker.arn
  batch_size       = 1
  enabled          = true

  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = var.event_source_max_concurrency
  }
}
