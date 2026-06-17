# Terraform + provider pinning and remote-state wiring (infra-spec §6).
#
# Remote state is an S3 backend with DynamoDB-based state locking. No bucket / account is
# hardcoded — supply it at init time so the same code promotes across accounts (Q1 option b):
#
#   terraform init -backend-config=backend.hcl
#
# For local authoring / CI validation only (no live state, org rule OOS-3 — never apply):
#
#   terraform init -backend=false
#   terraform fmt -check -recursive
#   terraform validate

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.100"
    }
  }

  # Partial backend config — bucket, key, region, dynamodb_table provided via -backend-config.
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}
