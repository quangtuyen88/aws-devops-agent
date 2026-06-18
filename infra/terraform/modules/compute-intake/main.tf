# compute-intake — always-on intake role (infra-spec §2.1). API Gateway HTTP API → intake
# Lambda (Slack signature verify, dedup register, ack, enqueue; also synchronous reactions).
# No VPC (protects the NFR-1 ack p95 < 3s by avoiding ENI cold-start). Provisioned
# concurrency bounds the cold-start tail. A published version + alias enables blue/green.

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

resource "aws_lambda_function" "intake" {
  function_name = "${var.name_prefix}-intake"
  role          = var.role_arn
  runtime       = var.runtime
  handler       = "slack_devops_agent.entrypoints.lambda_intake.lambda_handler"
  timeout       = 10
  memory_size   = 512
  publish       = true

  s3_bucket = var.artifact_s3_bucket
  s3_key    = var.artifact_s3_key

  environment {
    variables = {
      PROCESSING_JOB_TABLE        = var.table_processing_job
      OPERATIONAL_DATA_TABLE      = var.table_operational
      CONFIG_TABLE                = var.table_config
      ANSWER_TS_GSI               = var.answer_ts_index
      WORK_QUEUE_URL              = var.work_queue_url
      HEARTBEAT_SECONDS           = tostring(var.heartbeat_seconds)
      LEASE_STALENESS_SECONDS     = tostring(var.lease_staleness_seconds)
      REQUEST_TIME_BUDGET_SECONDS = tostring(var.request_budget_seconds)
      MAX_ATTEMPTS                = tostring(var.max_attempts)
      SLACK_SIGNING_SECRET        = var.slack_signing_secret
      SLACK_BOT_TOKEN             = var.slack_bot_token
      SLACK_BOT_USER_ID           = var.slack_bot_user_id
    }
  }

  tags = var.tags
}

resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.intake.function_name
  function_version = aws_lambda_function.intake.version
}

resource "aws_lambda_provisioned_concurrency_config" "intake" {
  count                             = var.provisioned_concurrency > 0 ? 1 : 0
  function_name                     = aws_lambda_function.intake.function_name
  qualifier                         = aws_lambda_alias.live.name
  provisioned_concurrent_executions = var.provisioned_concurrency
}

# --- API Gateway HTTP API (only public ingress; authed by Slack signature in the handler) ---

resource "aws_apigatewayv2_api" "this" {
  name          = "${var.name_prefix}-slack-events"
  protocol_type = "HTTP"
  tags          = var.tags
}

resource "aws_apigatewayv2_integration" "intake" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_alias.live.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "events" {
  api_id    = aws_apigatewayv2_api.this.id
  route_key = "POST /slack/events"
  target    = "integrations/${aws_apigatewayv2_integration.intake.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true
  tags        = var.tags
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.intake.function_name
  qualifier     = aws_lambda_alias.live.name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}
