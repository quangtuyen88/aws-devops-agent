# recovery — EventBridge Scheduler → reaper Lambda (infra-spec §1/§6, F3). No VPC. Periodic
# stale-lease recovery + DLQ drain; abandons exhausted jobs to `failed` and posts the FR-17
# in-thread message (BR-021/BR-022). A scheduler-invoke role lets EventBridge call the Lambda.

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

resource "aws_lambda_function" "reaper" {
  function_name = "${var.name_prefix}-reaper"
  role          = var.role_arn
  runtime       = var.runtime
  handler       = "slack_devops_agent.entrypoints.lambda_reaper.lambda_handler"
  timeout       = 60
  memory_size   = 512

  s3_bucket = var.artifact_s3_bucket
  s3_key    = var.artifact_s3_key

  environment {
    variables = {
      PROCESSING_JOB_TABLE    = var.table_processing_job
      DLQ_URL                 = var.dlq_url
      LEASE_STALENESS_SECONDS = tostring(var.lease_staleness_seconds)
      MAX_ATTEMPTS            = tostring(var.max_attempts)
    }
  }

  tags = var.tags
}

# Role allowing EventBridge Scheduler to invoke the reaper.
data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name_prefix}-reaper-scheduler-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "scheduler_invoke" {
  statement {
    sid       = "InvokeReaper"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.reaper.arn]
  }
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name   = "invoke-reaper"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_invoke.json
}

resource "aws_scheduler_schedule" "reaper" {
  name = "${var.name_prefix}-reaper-schedule"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = var.schedule_expression

  target {
    arn      = aws_lambda_function.reaper.arn
    role_arn = aws_iam_role.scheduler.arn
  }
}
