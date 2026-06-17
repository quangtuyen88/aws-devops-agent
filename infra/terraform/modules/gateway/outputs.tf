output "alb_dns_name" {
  description = "Internal ALB DNS name fronting the kiro-gateway service (created or borrowed)."
  value       = var.use_existing_alb ? one(data.aws_lb.existing[*].dns_name) : one(aws_lb.this[*].dns_name)
}

output "cluster_name" {
  description = "ECS cluster name."
  value       = aws_ecs_cluster.this.name
}

output "service_name" {
  description = "ECS service name."
  value       = aws_ecs_service.this.name
}
