output "work_queue_url" {
  description = "Work queue URL."
  value       = aws_sqs_queue.work.id
}

output "work_queue_arn" {
  description = "Work queue ARN."
  value       = aws_sqs_queue.work.arn
}

output "dlq_url" {
  description = "Dead-letter queue URL."
  value       = aws_sqs_queue.dlq.id
}

output "dlq_arn" {
  description = "Dead-letter queue ARN."
  value       = aws_sqs_queue.dlq.arn
}
