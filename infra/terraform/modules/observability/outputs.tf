output "dashboard_name" {
  description = "CloudWatch dashboard name."
  value       = aws_cloudwatch_dashboard.this.dashboard_name
}

output "log_group_names" {
  description = "Map of role -> Lambda log group name."
  value       = { for k, lg in aws_cloudwatch_log_group.lambda : k => lg.name }
}
