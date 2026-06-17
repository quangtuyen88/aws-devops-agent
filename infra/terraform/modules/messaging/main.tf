# messaging — C-1 intake->worker queue + DLQ (infra-spec §1/§2.4). Standard SQS, KMS SSE.
# Visibility timeout == lease staleness (90s) so redelivery aligns with lease reclaim;
# maxReceiveCount == max attempts (3) → DLQ, drained by the recovery reaper (BR-022).

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

resource "aws_sqs_queue" "dlq" {
  name                      = var.dlq_name
  kms_master_key_id         = var.kms_key_arn
  message_retention_seconds = 1209600 # 14 days — give the reaper ample drain window
  tags                      = var.tags
}

resource "aws_sqs_queue" "work" {
  name                       = var.work_queue_name
  kms_master_key_id          = var.kms_key_arn
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = 345600 # 4 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.max_receive_count
  })

  tags = var.tags
}

# Allow only the work queue to redrive into the DLQ.
resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.work.arn]
  })
}
