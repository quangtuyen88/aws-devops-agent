output "kms_key_arn" {
  description = "Customer-managed KMS key ARN."
  value       = aws_kms_key.app.arn
}

output "intake_role_arn" {
  description = "intake-lambda-role ARN."
  value       = aws_iam_role.intake.arn
}

output "worker_role_arn" {
  description = "worker-lambda-role ARN."
  value       = aws_iam_role.worker.arn
}

output "reaper_role_arn" {
  description = "reaper-lambda-role ARN."
  value       = aws_iam_role.reaper.arn
}

output "gateway_task_role_arn" {
  description = "kiro-gateway task role ARN."
  value       = aws_iam_role.gateway_task.arn
}

output "gateway_execution_role_arn" {
  description = "kiro-gateway ECS execution role ARN."
  value       = aws_iam_role.gateway_execution.arn
}

output "secret_arns" {
  description = "Map of logical secret name -> Secrets Manager ARN."
  value       = { for k, s in aws_secretsmanager_secret.this : k => s.arn }
}
