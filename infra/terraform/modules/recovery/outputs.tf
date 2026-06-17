output "function_name" {
  description = "Reaper Lambda function name."
  value       = aws_lambda_function.reaper.function_name
}

output "schedule_name" {
  description = "EventBridge schedule name driving the recovery scan."
  value       = aws_scheduler_schedule.reaper.name
}
