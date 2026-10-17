# VPC with two AZs: public subnets hold one NAT gateway, private subnets hold
# EKS nodes, MSK brokers, ElastiCache and the VPC-attached Lambda functions.
# S3 and DynamoDB are reached through free gateway endpoints.

terraform {
  required_version = ">= 1.10"
  backend "s3" {
    key = "network/terraform.tfstate"
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "ride-dispatch"
      ManagedBy = "terraform"
    }
  }
}

locals {
  name = "ride-dispatch"
  # AZ IDs where every instance type used here is offered (checked in Phase 3).
  az_ids = ["use1-az1", "use1-az2"]
}

data "aws_availability_zones" "selected" {
  state = "available"
  filter {
    name   = "zone-id"
    values = local.az_ids
  }
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = local.name }
}

resource "aws_subnet" "public" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone = data.aws_availability_zones.selected.names[count.index]
  tags = {
    Name                     = "${local.name}-public-${count.index}"
    "kubernetes.io/role/elb" = "1"
  }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = data.aws_availability_zones.selected.names[count.index]
  tags = {
    Name                              = "${local.name}-private-${count.index}"
    "kubernetes.io/role/internal-elb" = "1"
  }
}

resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "${local.name}-nat" }
}

# One NAT gateway for both AZs: cheaper than one per AZ, acceptable for a demo.
resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  tags          = { Name = local.name }
  depends_on    = [aws_internet_gateway.main]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "${local.name}-public" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }
  tags = { Name = "${local.name}-private" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_vpc_endpoint" "gateway" {
  for_each          = toset(["s3", "dynamodb"])
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.${each.key}"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
  tags              = { Name = "${local.name}-${each.key}" }
}

# Security groups shared across stacks. Ingress from EKS nodes is added by the
# cluster stack, which owns the node security group.

resource "aws_security_group" "lambda" {
  name        = "${local.name}-lambda"
  description = "VPC-attached matching functions"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_egress_rule" "lambda_all" {
  security_group_id = aws_security_group.lambda.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
  description       = "Redis, MSK, OSRM in the VPC and EventBridge through the NAT gateway"
}

resource "aws_security_group" "msk" {
  name        = "${local.name}-msk"
  description = "MSK brokers, IAM authentication port only"
  vpc_id      = aws_vpc.main.id
}

# The Lambda event source mapping polls through ENIs that use this security group.
resource "aws_vpc_security_group_ingress_rule" "msk_self" {
  security_group_id            = aws_security_group.msk.id
  referenced_security_group_id = aws_security_group.msk.id
  ip_protocol                  = "tcp"
  from_port                    = 9098
  to_port                      = 9098
  description                  = "Event source mapping pollers"
}

resource "aws_vpc_security_group_ingress_rule" "msk_from_lambda" {
  security_group_id            = aws_security_group.msk.id
  referenced_security_group_id = aws_security_group.lambda.id
  ip_protocol                  = "tcp"
  from_port                    = 9098
  to_port                      = 9098
  description                  = "Matching function producing assignments"
}

resource "aws_vpc_security_group_egress_rule" "msk_all" {
  security_group_id = aws_security_group.msk.id
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
  description       = "Event source mapping pollers reach Lambda and STS through the NAT gateway"
}

resource "aws_security_group" "redis" {
  name        = "${local.name}-redis"
  description = "ElastiCache Redis, TLS port"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "redis_from_lambda" {
  security_group_id            = aws_security_group.redis.id
  referenced_security_group_id = aws_security_group.lambda.id
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
  description                  = "Matching functions"
}
