# observability — CloudWatch log groups, dashboard, and alarms (infra-spec §5, NFR-20).
# Logs are structured JSON keyed by correlation-id (= job-id); metrics arrive via EMF from
# the worker/intake logs. KMS-encrypted log groups, 30-day retention.

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

locals {
  functions = {
    intake = var.intake_function
    worker = var.worker_function
    reaper = var.reaper_function
  }
  metrics_namespace = "SlackDevOpsAgent/UNIT-001"
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each = local.functions

  name              = "/aws/lambda/${each.value}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
  tags              = var.tags
}

# DLQ depth alarm (NFR-19/NFR-20): any message on the DLQ means an abandoned job.
resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name          = "${var.name_prefix}-dlq-not-empty"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 0
  period              = 60
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = var.dlq_name
  }

  tags = var.tags
}

# Worker error-rate alarm (NFR-2/NFR-9).
resource "aws_cloudwatch_metric_alarm" "worker_errors" {
  alarm_name          = "${var.name_prefix}-worker-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 5
  period              = 300
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = var.worker_function
  }

  tags = var.tags
}

# Ack-latency p95 alarm (NFR-1, < 3s) — EMF custom metric emitted by intake.
resource "aws_cloudwatch_metric_alarm" "ack_latency_p95" {
  alarm_name          = "${var.name_prefix}-ack-latency-p95"
  namespace           = local.metrics_namespace
  metric_name         = "ack_latency"
  extended_statistic  = "p95"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 3000
  period              = 300
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"

  tags = var.tags
}

# Full-answer-latency p95 alarm (NFR-2, <= 30s) — EMF custom metric emitted by worker.
resource "aws_cloudwatch_metric_alarm" "answer_latency_p95" {
  alarm_name          = "${var.name_prefix}-answer-latency-p95"
  namespace           = local.metrics_namespace
  metric_name         = "full_answer_latency"
  extended_statistic  = "p95"
  comparison_operator = "GreaterThanThreshold"
  threshold           = 30000
  period              = 300
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"

  tags = var.tags
}

resource "aws_cloudwatch_dashboard" "this" {
  dashboard_name = "${var.name_prefix}-overview"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Latency p95 (ack vs full answer)"
          region = var.aws_region
          metrics = [
            [local.metrics_namespace, "ack_latency", { stat = "p95" }],
            [local.metrics_namespace, "full_answer_latency", { stat = "p95" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Failure by cause"
          region = var.aws_region
          metrics = [
            [local.metrics_namespace, "failure_by_cause", { stat = "Sum" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "Recovery: requeued vs abandoned"
          region = var.aws_region
          metrics = [
            [local.metrics_namespace, "recovery_requeued", { stat = "Sum" }],
            [local.metrics_namespace, "recovery_abandoned", { stat = "Sum" }],
          ]
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 6
        width  = 12
        height = 6
        properties = {
          title  = "DLQ depth"
          region = var.aws_region
          metrics = [
            ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", var.dlq_name],
          ]
        }
      },
    ]
  })
}
