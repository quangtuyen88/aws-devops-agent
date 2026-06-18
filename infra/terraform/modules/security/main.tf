# security — KMS CMK, Secrets Manager containers, and least-privilege IAM roles
# (infra-spec §4). One role per runtime role (intake/worker/reaper/gateway), each scoped to
# specific resource ARNs. IAM policies reference ARNs *constructed from the name prefix* so
# this module never consumes other modules' outputs (breaks the KMS<->ARN dependency cycle).

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "aws_partition" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name
  partition  = data.aws_partition.current.partition

  arn_table_processing_job = "arn:${local.partition}:dynamodb:${local.region}:${local.account_id}:table/${var.table_processing_job}"
  arn_table_operational    = "arn:${local.partition}:dynamodb:${local.region}:${local.account_id}:table/${var.table_operational}"
  arn_table_config         = "arn:${local.partition}:dynamodb:${local.region}:${local.account_id}:table/${var.table_config}"
  arn_work_queue           = "arn:${local.partition}:sqs:${local.region}:${local.account_id}:${var.work_queue_name}"
  arn_dlq                  = "arn:${local.partition}:sqs:${local.region}:${local.account_id}:${var.dlq_name}"
}

# --- Customer-managed KMS key (NFR-5: data/secrets/queues/logs at rest) ---

# Explicit key policy: keep root as key admin (preserves the IAM-grant path that DynamoDB,
# SQS, and Secrets Manager use), and add the CloudWatch Logs SERVICE principal so KMS-encrypted
# log groups can be created. Logs uses the CMK as the service itself, which the AWS default key
# policy does not grant — scoped here to this stack's log groups via an ArnLike condition.
data "aws_iam_policy_document" "kms_key" {
  statement {
    sid       = "EnableRootAccount"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:${local.partition}:iam::${local.account_id}:root"]
    }
  }

  statement {
    sid    = "AllowCloudWatchLogs"
    effect = "Allow"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
    ]
    resources = ["*"]
    principals {
      type        = "Service"
      identifiers = ["logs.${local.region}.amazonaws.com"]
    }
    condition {
      test     = "ArnLike"
      variable = "kms:EncryptionContext:aws:logs:arn"
      values   = ["arn:${local.partition}:logs:${local.region}:${local.account_id}:log-group:*"]
    }
  }
}

resource "aws_kms_key" "app" {
  description             = "${var.name_prefix} customer-managed key (DynamoDB, SQS, Secrets, Logs)"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  policy                  = data.aws_iam_policy_document.kms_key.json
  tags                    = var.tags
}

resource "aws_kms_alias" "app" {
  name          = "alias/${var.name_prefix}"
  target_key_id = aws_kms_key.app.key_id
}

# --- Secrets Manager containers (one per integration; values injected out of band, §4.1) ---

resource "aws_secretsmanager_secret" "this" {
  for_each = {
    slack_signing  = "slack/signing-secret"
    slack_bot      = "slack/bot-token"
    kiro_proxy_key = "inference/kiro-gateway-proxy-key"
    kiro_sso       = "inference/kiro-sso-credentials"
    mcp            = "mcp/aws-knowledge-credential"
  }

  name       = "${var.name_prefix}/${each.value}"
  kms_key_id = aws_kms_key.app.arn
  tags       = var.tags
}

# --- Assume-role policy documents ---

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Shared KMS-use statement (encrypt/decrypt against the app CMK).
data "aws_iam_policy_document" "kms_use" {
  statement {
    sid       = "UseAppKms"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = [aws_kms_key.app.arn]
  }
}

# --- intake-lambda-role (§4.2): SQS send, ProcessingJob R/W, OperationalData append+read,
#     Config read, Slack secrets read. No UpdateItem on OperationalData (feedback append-only). ---

data "aws_iam_policy_document" "intake" {
  statement {
    sid       = "EnqueueWork"
    actions   = ["sqs:SendMessage"]
    resources = [local.arn_work_queue]
  }
  statement {
    sid       = "ProcessingJobDedup"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"]
    resources = [local.arn_table_processing_job, "${local.arn_table_processing_job}/index/*"]
  }
  statement {
    sid       = "FeedbackAppendAndResolve"
    actions   = ["dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query"]
    resources = [local.arn_table_operational]
  }
  statement {
    sid       = "ConfigRead"
    actions   = ["dynamodb:GetItem", "dynamodb:Query"]
    resources = [local.arn_table_config]
  }
  statement {
    sid     = "SlackSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.this["slack_signing"].arn,
      aws_secretsmanager_secret.this["slack_bot"].arn,
    ]
  }
}

# --- worker-lambda-role (§4.2): SQS receive/delete, ProcessingJob+OperationalData R/W,
#     Config read, Bedrock invoke (specific model ARNs), kiro/mcp/slack secrets, VPC ENI. ---

data "aws_iam_policy_document" "worker" {
  statement {
    sid       = "ConsumeWork"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [local.arn_work_queue]
  }
  statement {
    sid = "JobAndOpData"
    actions = [
      "dynamodb:UpdateItem", "dynamodb:PutItem", "dynamodb:GetItem", "dynamodb:Query",
    ]
    resources = [
      local.arn_table_processing_job,
      "${local.arn_table_processing_job}/index/*",
      local.arn_table_operational,
    ]
  }
  statement {
    sid       = "ConfigRead"
    actions   = ["dynamodb:GetItem", "dynamodb:Query"]
    resources = [local.arn_table_config]
  }
  statement {
    sid     = "WorkerSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.this["kiro_proxy_key"].arn,
      aws_secretsmanager_secret.this["mcp"].arn,
      aws_secretsmanager_secret.this["slack_bot"].arn,
    ]
  }
  dynamic "statement" {
    for_each = length(var.bedrock_model_arns) > 0 ? [1] : []
    content {
      sid       = "BedrockInvoke"
      actions   = ["bedrock:InvokeModel", "bedrock:Converse"]
      resources = var.bedrock_model_arns
    }
  }
}

# --- reaper-lambda-role (§4.2/F3): ProcessingJob write, DLQ only, slack/bot-token only. ---

data "aws_iam_policy_document" "reaper" {
  statement {
    sid       = "AbandonJobs"
    actions   = ["dynamodb:UpdateItem", "dynamodb:GetItem", "dynamodb:Query", "dynamodb:Scan"]
    resources = [local.arn_table_processing_job, "${local.arn_table_processing_job}/index/*"]
  }
  statement {
    sid       = "DrainDlq"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [local.arn_dlq]
  }
  statement {
    sid       = "SlackBotToken"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.this["slack_bot"].arn]
  }
}

# --- kiro-gateway-task-role (§4.2): kiro-sso + proxy-key only; NO data-plane perms. ---

data "aws_iam_policy_document" "gateway_task" {
  statement {
    sid     = "GatewaySecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.this["kiro_sso"].arn,
      aws_secretsmanager_secret.this["kiro_proxy_key"].arn,
    ]
  }
}

# --- Role + inline-policy wiring ---

resource "aws_iam_role" "intake" {
  name               = "${var.name_prefix}-intake-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "intake" {
  name   = "intake-least-privilege"
  role   = aws_iam_role.intake.id
  policy = data.aws_iam_policy_document.intake.json
}

resource "aws_iam_role_policy" "intake_kms" {
  name   = "intake-kms"
  role   = aws_iam_role.intake.id
  policy = data.aws_iam_policy_document.kms_use.json
}

resource "aws_iam_role_policy_attachment" "intake_logs" {
  role       = aws_iam_role.intake.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role" "worker" {
  name               = "${var.name_prefix}-worker-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "worker" {
  name   = "worker-least-privilege"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker.json
}

resource "aws_iam_role_policy" "worker_kms" {
  name   = "worker-kms"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.kms_use.json
}

resource "aws_iam_role_policy_attachment" "worker_logs" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Worker runs in a VPC and needs managed ENI permissions.
resource "aws_iam_role_policy_attachment" "worker_vpc" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role" "reaper" {
  name               = "${var.name_prefix}-reaper-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "reaper" {
  name   = "reaper-least-privilege"
  role   = aws_iam_role.reaper.id
  policy = data.aws_iam_policy_document.reaper.json
}

resource "aws_iam_role_policy" "reaper_kms" {
  name   = "reaper-kms"
  role   = aws_iam_role.reaper.id
  policy = data.aws_iam_policy_document.kms_use.json
}

resource "aws_iam_role_policy_attachment" "reaper_logs" {
  role       = aws_iam_role.reaper.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role" "gateway_task" {
  name               = "${var.name_prefix}-gateway-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "gateway_task" {
  name   = "gateway-secrets"
  role   = aws_iam_role.gateway_task.id
  policy = data.aws_iam_policy_document.gateway_task.json
}

resource "aws_iam_role_policy" "gateway_task_kms" {
  name   = "gateway-kms"
  role   = aws_iam_role.gateway_task.id
  policy = data.aws_iam_policy_document.kms_use.json
}

# ECS execution role — pull image + write logs + read the secrets injected as container env.
resource "aws_iam_role" "gateway_execution" {
  name               = "${var.name_prefix}-gateway-execution-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "gateway_execution" {
  role       = aws_iam_role.gateway_execution.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "gateway_execution_secrets" {
  statement {
    sid     = "InjectGatewaySecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.this["kiro_sso"].arn,
      aws_secretsmanager_secret.this["kiro_proxy_key"].arn,
    ]
  }
  statement {
    sid       = "DecryptSecrets"
    actions   = ["kms:Decrypt"]
    resources = [aws_kms_key.app.arn]
  }
}

resource "aws_iam_role_policy" "gateway_execution_secrets" {
  name   = "gateway-execution-secrets"
  role   = aws_iam_role.gateway_execution.id
  policy = data.aws_iam_policy_document.gateway_execution_secrets.json
}
