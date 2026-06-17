# Root outputs — the operationally useful handles after a deploy.

output "slack_events_api_endpoint" {
  description = "API Gateway HTTPS endpoint to register as the Slack Events request URL."
  value       = module.compute_intake.api_endpoint
}

output "work_queue_url" {
  description = "C-1 intake->worker SQS queue URL."
  value       = module.messaging.work_queue_url
}

output "dlq_url" {
  description = "Dead-letter queue URL (drained by the recovery reaper)."
  value       = module.messaging.dlq_url
}

output "processing_job_table" {
  description = "ProcessingJob DynamoDB table name."
  value       = module.data.processing_job_table_name
}

output "gateway_internal_endpoint" {
  description = "Internal ALB DNS name fronting the kiro-gateway Fargate service."
  value       = module.gateway.alb_dns_name
}

output "kms_key_arn" {
  description = "Customer-managed KMS key ARN protecting data/secrets/queues/logs."
  value       = module.security.kms_key_arn
}
