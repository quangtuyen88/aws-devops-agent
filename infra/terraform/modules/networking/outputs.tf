output "vpc_id" {
  description = "Worker VPC ID (created or borrowed)."
  value       = local.vpc_id
}

output "private_subnet_ids" {
  description = "Private subnet IDs (worker Lambda + Fargate) — created or borrowed."
  value       = local.private_subnet_ids
}

output "public_subnet_ids" {
  description = "Public subnet IDs (NAT). Empty in existing-network mode."
  value       = aws_subnet.public[*].id
}

output "worker_sg_id" {
  description = "Worker / in-VPC compute security group ID (created or first borrowed SG)."
  value       = var.use_existing_network ? try(var.existing_security_group_ids[0], null) : one(aws_security_group.worker[*].id)
}
