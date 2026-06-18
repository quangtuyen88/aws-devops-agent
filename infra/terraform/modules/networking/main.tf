# networking — worker VPC, private/public subnets, NAT, and VPC endpoints (infra-spec §3).
# The worker Lambda runs in private subnets; external HTTPS egress (Slack/MCP) via NAT,
# AWS APIs via interface/gateway VPC endpoints (keeps that traffic off NAT and IAM-scoped).
#
# ============================================================================
# DESTROY-SAFETY GUARANTEE (existing-VPC mode, use_existing_network = true)
# ============================================================================
# When use_existing_network = true this module consumes a pre-existing VPC, subnets, and
# security group(s) STRICTLY through DATA SOURCES / by-ID references (data.aws_vpc,
# data.aws_subnet, data.aws_security_group, data.aws_route_tables). The pre-existing VPC /
# subnets / SG / NAT are NEVER declared as managed `resource` blocks here, so Terraform
# does not own them: `terraform destroy` removes ONLY app-created resources (the VPC
# endpoints we created, the endpoint SG, Lambdas, SQS, DynamoDB, ECS, IAM, secrets) and can
# NEVER delete the borrowed VPC, subnets, security group, or NAT gateway.
#
# When use_existing_network = false (default) the module keeps today's behavior: it CREATES
# and owns the VPC, subnets, NAT, route tables, and worker SG.
# ============================================================================

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)

  # Mode switches. create_network gates every managed network resource; existing infra is
  # only ever read via data sources (see destroy-safety guarantee above).
  create_network = !var.use_existing_network
  create_nat     = local.create_network && !var.existing_nat_gateway

  # At least one interface endpoint requested ⇒ we need the endpoint security group.
  any_interface_endpoint = (
    var.create_sqs_endpoint ||
    var.create_secretsmanager_endpoint ||
    var.create_logs_endpoint ||
    var.create_ecr_api_endpoint ||
    var.create_ecr_dkr_endpoint ||
    var.create_bedrock_endpoint
  )

  # Resolved handles — created resources OR borrowed (data-source) ones, never mixed.
  vpc_id         = var.use_existing_network ? one(data.aws_vpc.existing[*].id) : one(aws_vpc.this[*].id)
  vpc_cidr_block = var.use_existing_network ? one(data.aws_vpc.existing[*].cidr_block) : var.vpc_cidr

  private_subnet_ids = var.use_existing_network ? var.existing_private_subnet_ids : aws_subnet.private[*].id

  private_route_table_ids = var.use_existing_network ? (
    one(data.aws_route_tables.existing[*].ids)
  ) : aws_route_table.private[*].id
}

# --- Existing-network data sources (read-only, by-ID; used only when borrowing) ---

data "aws_vpc" "existing" {
  count = var.use_existing_network ? 1 : 0
  id    = var.existing_vpc_id
}

data "aws_subnet" "existing" {
  for_each = var.use_existing_network ? toset(var.existing_private_subnet_ids) : toset([])
  id       = each.value
}

data "aws_security_group" "existing" {
  for_each = var.use_existing_network ? toset(var.existing_security_group_ids) : toset([])
  id       = each.value
}

# Private route tables of the borrowed VPC — needed to attach the free gateway endpoints.
data "aws_route_tables" "existing" {
  count  = var.use_existing_network ? 1 : 0
  vpc_id = var.existing_vpc_id
}

# --- Managed network (created only when use_existing_network = false) ---

resource "aws_vpc" "this" {
  count                = local.create_network ? 1 : 0
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(var.tags, { Name = "${var.name_prefix}-vpc" })
}

resource "aws_internet_gateway" "this" {
  count  = local.create_network ? 1 : 0
  vpc_id = aws_vpc.this[0].id
  tags   = merge(var.tags, { Name = "${var.name_prefix}-igw" })
}

resource "aws_subnet" "public" {
  count                   = local.create_network ? var.az_count : 0
  vpc_id                  = aws_vpc.this[0].id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true
  tags                    = merge(var.tags, { Name = "${var.name_prefix}-public-${count.index}" })
}

resource "aws_subnet" "private" {
  count             = local.create_network ? var.az_count : 0
  vpc_id            = aws_vpc.this[0].id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 100)
  availability_zone = local.azs[count.index]
  tags              = merge(var.tags, { Name = "${var.name_prefix}-private-${count.index}" })
}

# Single NAT gateway (cost note in infra-spec §3 — the main always-on cost of the VPC
# posture). Skipped when borrowing a NAT (existing_nat_gateway) or an existing VPC.
resource "aws_eip" "nat" {
  count  = local.create_nat ? 1 : 0
  domain = "vpc"
  tags   = merge(var.tags, { Name = "${var.name_prefix}-nat-eip" })
}

resource "aws_nat_gateway" "this" {
  count         = local.create_nat ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id
  tags          = merge(var.tags, { Name = "${var.name_prefix}-nat" })
  depends_on    = [aws_internet_gateway.this]
}

resource "aws_route_table" "public" {
  count  = local.create_network ? 1 : 0
  vpc_id = aws_vpc.this[0].id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this[0].id
  }
  tags = merge(var.tags, { Name = "${var.name_prefix}-public-rt" })
}

resource "aws_route_table_association" "public" {
  count          = local.create_network ? var.az_count : 0
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}

resource "aws_route_table" "private" {
  count  = local.create_network ? 1 : 0
  vpc_id = aws_vpc.this[0].id

  dynamic "route" {
    for_each = local.create_nat ? [1] : []
    content {
      cidr_block     = "0.0.0.0/0"
      nat_gateway_id = aws_nat_gateway.this[0].id
    }
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-private-rt" })
}

resource "aws_route_table_association" "private" {
  count          = local.create_network ? var.az_count : 0
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[0].id
}

# --- Security groups ---

# Worker SG — created only when we own the network. In existing-VPC mode the worker uses the
# caller-supplied existing_security_group_ids (read via data.aws_security_group.existing).
resource "aws_security_group" "worker" {
  count       = local.create_network ? 1 : 0
  name        = "${var.name_prefix}-worker-sg"
  description = "Worker Lambda ENIs - outbound HTTPS only."
  vpc_id      = aws_vpc.this[0].id

  egress {
    description = "All outbound (HTTPS to Slack/MCP via NAT, AWS APIs via endpoints)."
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-worker-sg" })
}

# Endpoint SG is always app-created (destroy-safe) whenever any interface endpoint is enabled,
# attached to the resolved VPC (created or borrowed).
resource "aws_security_group" "endpoints" {
  count       = local.any_interface_endpoint ? 1 : 0
  name        = "${var.name_prefix}-vpce-sg"
  description = "Interface VPC endpoints - accept 443 from inside the VPC."
  vpc_id      = local.vpc_id

  ingress {
    description = "HTTPS from within the VPC."
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [local.vpc_cidr_block]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-vpce-sg" })
}

# --- VPC endpoints (all app-created → removed cleanly on destroy) ---

# Gateway endpoints (free) for DynamoDB and S3 — always created, attached to the private
# route tables (created or borrowed).
resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id            = local.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = local.private_route_table_ids
  tags              = merge(var.tags, { Name = "${var.name_prefix}-vpce-dynamodb" })
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = local.vpc_id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = local.private_route_table_ids
  tags              = merge(var.tags, { Name = "${var.name_prefix}-vpce-s3" })
}

# Interface endpoints — each individually toggleable. Keeps the named AWS API traffic off NAT
# and IAM-scoped. count = var.X ? 1 : 0 per endpoint.
resource "aws_vpc_endpoint" "sqs" {
  count               = var.create_sqs_endpoint ? 1 : 0
  vpc_id              = local.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.sqs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.private_subnet_ids
  security_group_ids  = [aws_security_group.endpoints[0].id]
  private_dns_enabled = true
  tags                = merge(var.tags, { Name = "${var.name_prefix}-vpce-sqs" })
}

resource "aws_vpc_endpoint" "secretsmanager" {
  count               = var.create_secretsmanager_endpoint ? 1 : 0
  vpc_id              = local.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.private_subnet_ids
  security_group_ids  = [aws_security_group.endpoints[0].id]
  private_dns_enabled = true
  tags                = merge(var.tags, { Name = "${var.name_prefix}-vpce-secretsmanager" })
}

resource "aws_vpc_endpoint" "logs" {
  count               = var.create_logs_endpoint ? 1 : 0
  vpc_id              = local.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.logs"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.private_subnet_ids
  security_group_ids  = [aws_security_group.endpoints[0].id]
  private_dns_enabled = true
  tags                = merge(var.tags, { Name = "${var.name_prefix}-vpce-logs" })
}

resource "aws_vpc_endpoint" "ecr_api" {
  count               = var.create_ecr_api_endpoint ? 1 : 0
  vpc_id              = local.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.ecr.api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.private_subnet_ids
  security_group_ids  = [aws_security_group.endpoints[0].id]
  private_dns_enabled = true
  tags                = merge(var.tags, { Name = "${var.name_prefix}-vpce-ecr-api" })
}

resource "aws_vpc_endpoint" "ecr_dkr" {
  count               = var.create_ecr_dkr_endpoint ? 1 : 0
  vpc_id              = local.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.ecr.dkr"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.private_subnet_ids
  security_group_ids  = [aws_security_group.endpoints[0].id]
  private_dns_enabled = true
  tags                = merge(var.tags, { Name = "${var.name_prefix}-vpce-ecr-dkr" })
}

# Bedrock runtime endpoint — DEFAULT OFF. Bedrock is only the failover inference path; its
# traffic egresses via NAT unless compliance requires PrivateLink, in which case flip
# create_bedrock_endpoint = true to keep Bedrock calls on a private interface endpoint.
resource "aws_vpc_endpoint" "bedrock" {
  count               = var.create_bedrock_endpoint ? 1 : 0
  vpc_id              = local.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = local.private_subnet_ids
  security_group_ids  = [aws_security_group.endpoints[0].id]
  private_dns_enabled = true
  tags                = merge(var.tags, { Name = "${var.name_prefix}-vpce-bedrock-runtime" })
}
