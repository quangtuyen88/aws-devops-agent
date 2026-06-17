output "api_endpoint" {
  description = "Slack Events request URL base (append /slack/events)."
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "function_name" {
  description = "Intake Lambda function name."
  value       = aws_lambda_function.intake.function_name
}
