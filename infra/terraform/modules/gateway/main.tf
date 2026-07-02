# gateway — kiro-gateway on ECS Fargate behind an internal ALB (infra-spec §2.3). Always-on,
# stateful (holds/refreshes Kiro SSO tokens), private-only. Baseline 2 tasks across 2 AZs
# (Multi-AZ, F4). The upstream image is unmodified and never vendored (AGPL boundary, §0).
#
# DESTROY-SAFETY (existing-ALB mode, use_existing_alb = true): the pre-existing ALB and its
# HTTPS listener are referenced via DATA SOURCES / by-ARN only (data.aws_lb_listener,
# data.aws_lb). We add a managed aws_lb_listener_rule onto the borrowed listener instead of
# creating an ALB — destroy removes only that rule (and our target group / service), never the
# borrowed ALB or listener. When use_existing_alb = false (default) we create the ALB as today.

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

locals {
  # kiro-gateway listens on 8000 (upstream default; verified by local smoke test).
  container_port = 8000

  # Credentials are materialized to a task-local shared volume by an init container, then read
  # by the (unmodified) gateway via KIRO_CREDS_FILE — the secret never lives in the image.
  creds_volume = "kiro-creds"
  creds_dir    = "/creds"
  creds_file   = "/creds/kiro-auth-token.json"

  # Security group(s) that may reach the gateway tasks: our created ALB SG, or (existing-ALB
  # mode) the SGs attached to the borrowed ALB.
  alb_ingress_sg_ids = var.use_existing_alb ? (
    tolist(one(data.aws_lb.existing[*].security_groups))
  ) : aws_security_group.alb[*].id
}

# --- Existing-ALB data sources (read-only, by-ARN; used only when borrowing) ---

data "aws_lb_listener" "existing" {
  count = var.use_existing_alb ? 1 : 0
  arn   = var.existing_alb_listener_arn
}

data "aws_lb" "existing" {
  count = var.use_existing_alb ? 1 : 0
  arn   = data.aws_lb_listener.existing[0].load_balancer_arn
}

resource "aws_ecs_cluster" "this" {
  name = "${var.name_prefix}-gateway"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = var.tags
}

# --- Security groups: ALB accepts the worker SG on the listener port; tasks accept only from
# the ALB. Listener port is 443 (TLS) or 80 (plaintext, internal-only) per var.tls_enabled. ---

resource "aws_security_group" "alb" {
  count = var.use_existing_alb ? 0 : 1
  name  = "${var.name_prefix}-gateway-alb-sg"
  # NOTE: AWS SG descriptions are immutable — changing this text forces a destroy/recreate of
  # the live ALB SG. Kept verbatim to avoid that churn; the real port is in the ingress rule
  # description below (HTTP/80 or HTTPS/443 per tls_enabled).
  description = "Internal ALB for kiro-gateway - 443 from the worker SG only."
  vpc_id      = var.vpc_id

  ingress {
    description     = var.tls_enabled ? "HTTPS from the worker Lambda." : "HTTP from the worker Lambda."
    from_port       = var.tls_enabled ? 443 : 80
    to_port         = var.tls_enabled ? 443 : 80
    protocol        = "tcp"
    security_groups = [var.worker_sg_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-gateway-alb-sg" })
}

resource "aws_security_group" "service" {
  name        = "${var.name_prefix}-gateway-svc-sg"
  description = "kiro-gateway tasks - accept only from the internal ALB."
  vpc_id      = var.vpc_id

  ingress {
    description     = "Container port from the ALB."
    from_port       = local.container_port
    to_port         = local.container_port
    protocol        = "tcp"
    security_groups = local.alb_ingress_sg_ids
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(var.tags, { Name = "${var.name_prefix}-gateway-svc-sg" })
}

# --- Internal ALB + TLS listener (NFR-5 in-transit). Created only when not borrowing. ---

resource "aws_lb" "this" {
  count              = var.use_existing_alb ? 0 : 1
  name               = "${var.name_prefix}-gw-alb"
  internal           = true
  load_balancer_type = "application"
  subnets            = var.private_subnet_ids
  security_groups    = [aws_security_group.alb[0].id]
  # Must be >= the kiro gateway HTTP client timeout, else the ALB 504s a still-running
  # inference before the app-level timeout can act (default 60s is below the 70/75/85 chain).
  idle_timeout = var.alb_idle_timeout_seconds
  tags         = var.tags
}

# Target group is always app-created (and removed cleanly on destroy in either mode).
resource "aws_lb_target_group" "this" {
  name        = "${var.name_prefix}-gw-tg"
  port        = local.container_port
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = var.tags
}

resource "aws_lb_listener" "https" {
  count             = (!var.use_existing_alb && var.tls_enabled) ? 1 : 0
  load_balancer_arn = aws_lb.this[0].arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}

# Plaintext HTTP listener — internal-only path (private subnets, worker SG → ALB). Created
# when tls_enabled = false to avoid an ACM cert on the internal hop; flip tls_enabled to
# restore the 443/TLS listener (NFR-5).
resource "aws_lb_listener" "http" {
  count             = (!var.use_existing_alb && !var.tls_enabled) ? 1 : 0
  load_balancer_arn = aws_lb.this[0].arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}

# Existing-ALB mode: add a forwarding rule onto the borrowed listener (destroy removes only
# this rule, never the listener/ALB).
resource "aws_lb_listener_rule" "this" {
  count        = var.use_existing_alb ? 1 : 0
  listener_arn = var.existing_alb_listener_arn
  priority     = var.existing_alb_listener_rule_priority

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }

  condition {
    path_pattern {
      values = ["/*"]
    }
  }

  tags = var.tags
}

# --- Log group + task definition + service ---

resource "aws_cloudwatch_log_group" "gateway" {
  name              = "/ecs/${var.name_prefix}-gateway"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.kms_key_arn
  tags              = var.tags
}

resource "aws_ecs_task_definition" "this" {
  family                   = "${var.name_prefix}-gateway"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  task_role_arn            = var.task_role_arn
  execution_role_arn       = var.execution_role_arn

  # Task-local scratch volume shared between the init container (writes creds) and the gateway
  # (reads them). Ephemeral — never persisted, nothing baked into any image (AGPL boundary §0).
  volume {
    name = local.creds_volume
  }

  container_definitions = jsonencode([
    # Init container: writes the Kiro OIDC credentials JSON (injected from Secrets Manager) to
    # the shared volume, then exits. The gateway image is NOT modified — this stock image just
    # materializes the file the gateway expects at KIRO_CREDS_FILE.
    {
      name      = "kiro-creds-init"
      image     = var.creds_init_image
      essential = false
      command = [
        "sh", "-c",
        "set -eu; printf '%s' \"$KIRO_CREDS_JSON\" > ${local.creds_file}; echo 'wrote ${local.creds_file}'",
      ]
      secrets = [
        {
          name      = "KIRO_CREDS_JSON"
          valueFrom = var.sso_secret
        }
      ]
      mountPoints = [
        {
          sourceVolume  = local.creds_volume
          containerPath = local.creds_dir
          readOnly      = false
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.gateway.name
          "awslogs-region"        = data.aws_region.current.name
          "awslogs-stream-prefix" = "kiro-creds-init"
        }
      }
    },
    {
      name      = "kiro-gateway"
      image     = var.image
      essential = true
      portMappings = [
        {
          containerPort = local.container_port
          protocol      = "tcp"
        }
      ]
      # KIRO_CREDS_FILE points at the OIDC JSON written by the init container. The OIDC path
      # (clientId/clientSecret in the JSON) needs no profileArn. PROXY_API_KEY stays a secret.
      environment = [
        {
          name  = "KIRO_CREDS_FILE"
          value = local.creds_file
        }
      ]
      secrets = [
        {
          name      = "PROXY_API_KEY"
          valueFrom = var.proxy_key_secret
        }
      ]
      mountPoints = [
        {
          sourceVolume  = local.creds_volume
          containerPath = local.creds_dir
          readOnly      = false
        }
      ]
      dependsOn = [
        {
          containerName = "kiro-creds-init"
          condition     = "SUCCESS"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.gateway.name
          "awslogs-region"        = data.aws_region.current.name
          "awslogs-stream-prefix" = "kiro-gateway"
        }
      }
    }
  ])

  tags = var.tags
}

data "aws_region" "current" {}

resource "aws_ecs_service" "this" {
  name            = "${var.name_prefix}-gateway"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.this.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.service.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.this.arn
    container_name   = "kiro-gateway"
    container_port   = local.container_port
  }

  # Auto-rollback on a failed rollout (infra-spec §6 deployment-circuit-breaker).
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.https, aws_lb_listener.http, aws_lb_listener_rule.this]
}

# --- Application Auto Scaling: baseline 2 → max 4 on average CPU (infra-spec §2.3/§1, F4). ---
# kiro-gateway is the PRIMARY inference path and is our own infrastructure; target-tracking on
# CPU absorbs load spikes above the Multi-AZ baseline without manual intervention.

resource "aws_appautoscaling_target" "gateway" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.this.name}/${aws_ecs_service.this.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = var.autoscale_min_capacity
  max_capacity       = var.autoscale_max_capacity
}

resource "aws_appautoscaling_policy" "gateway_cpu" {
  name               = "${var.name_prefix}-gateway-cpu-tt"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.gateway.service_namespace
  resource_id        = aws_appautoscaling_target.gateway.resource_id
  scalable_dimension = aws_appautoscaling_target.gateway.scalable_dimension

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }

    target_value = var.autoscale_cpu_target
  }
}
