output "processing_job_table_name" {
  description = "ProcessingJob table name."
  value       = aws_dynamodb_table.processing_job.name
}

output "processing_job_table_arn" {
  description = "ProcessingJob table ARN."
  value       = aws_dynamodb_table.processing_job.arn
}

output "operational_data_table_name" {
  description = "OperationalData table name."
  value       = aws_dynamodb_table.operational_data.name
}

output "config_table_name" {
  description = "Config table name."
  value       = aws_dynamodb_table.config.name
}

output "answer_ts_index" {
  description = "Answer-ts GSI name."
  value       = var.answer_ts_index
}
