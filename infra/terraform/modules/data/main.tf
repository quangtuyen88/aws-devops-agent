# data — the three DynamoDB tables (infra-spec §1). All PAY_PER_REQUEST, KMS-encrypted at
# rest with the app CMK, point-in-time recovery on for durable job/op state (CS-2).

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

# ProcessingJob (CMP-006). PK = slack-event-identity ("channel#message-ts") in attribute `pk`
# (conditional PutItem dedup, F1). `job_id` is a stamped immutable correlation-id attribute.
# F8: GSI `answer-ts-index` keyed on `answer_message_ts`, PROJECTING `job_id` so intake can
# resolve a reaction's answer ts back to the correlation-id without a full-item read.
resource "aws_dynamodb_table" "processing_job" {
  name         = var.table_processing_job
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "answer_message_ts"
    type = "S"
  }

  global_secondary_index {
    name               = var.answer_ts_index
    hash_key           = "answer_message_ts"
    projection_type    = "INCLUDE"
    non_key_attributes = ["job_id"]
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = var.tags
}

# OperationalData (CMP-007). Composite key supports usage counters, adoption aggregates, and
# the append-only feedback rows (BR-019/BR-020).
resource "aws_dynamodb_table" "operational_data" {
  name         = var.table_operational
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = var.tags
}

# Config (CMP-008). Read-mostly allowlist / usage-policy / guardrail thresholds.
resource "aws_dynamodb_table" "config" {
  name         = var.table_config
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"

  attribute {
    name = "pk"
    type = "S"
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = var.tags
}
