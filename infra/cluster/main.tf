# EKS cluster for the long-lived workloads: OSRM (road graph in memory) and the
# driver simulator. One t4g.medium Graviton node in a private subnet.

terraform {
  required_version = ">= 1.10"
  backend "s3" {
    key = "cluster/terraform.tfstate"
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
  name      = "ride-dispatch"
  partition = data.aws_partition.current.partition
  account   = data.aws_caller_identity.current.account_id
  # The MSK cluster UUID is only known after the data stack is applied; the
  # wildcard is limited to that segment so both stacks can be applied in parallel.
  msk_cluster = "arn:${local.partition}:kafka:${var.region}:${local.account}:cluster/${local.name}/*"
  msk_topic   = "arn:${local.partition}:kafka:${var.region}:${local.account}:topic/${local.name}/*"
  msk_group   = "arn:${local.partition}:kafka:${var.region}:${local.account}:group/${local.name}/*"
  event_bus   = "arn:${local.partition}:events:${var.region}:${local.account}:event-bus/${local.name}"
}

data "aws_partition" "current" {}
data "aws_caller_identity" "current" {}

data "aws_vpc" "main" {
  tags = { Name = local.name }
}

data "aws_subnets" "private" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.main.id]
  }
  tags = { "kubernetes.io/role/internal-elb" = "1" }
}

data "aws_security_group" "msk" {
  name   = "${local.name}-msk"
  vpc_id = data.aws_vpc.main.id
}

data "aws_security_group" "redis" {
  name   = "${local.name}-redis"
  vpc_id = data.aws_vpc.main.id
}

data "aws_security_group" "lambda" {
  name   = "${local.name}-lambda"
  vpc_id = data.aws_vpc.main.id
}

# Control plane

data "aws_iam_policy_document" "eks_assume" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name               = "${local.name}-eks-cluster"
  assume_role_policy = data.aws_iam_policy_document.eks_assume.json
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_eks_cluster" "main" {
  name     = local.name
  version  = var.eks_version
  role_arn = aws_iam_role.cluster.arn

  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = true
  }

  vpc_config {
    subnet_ids              = data.aws_subnets.private.ids
    endpoint_private_access = true
    endpoint_public_access  = true
    # Public API endpoint reachable only from the operator's address.
    public_access_cidrs = var.admin_cidrs
  }

  depends_on = [aws_iam_role_policy_attachment.cluster]
}

# Nodes

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = "${local.name}-eks-node"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = toset([
    "AmazonEKSWorkerNodePolicy",
    "AmazonEKS_CNI_Policy",
    "AmazonEC2ContainerRegistryReadOnly",
  ])
  role       = aws_iam_role.node.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/${each.key}"
}

resource "aws_eks_node_group" "main" {
  cluster_name    = aws_eks_cluster.main.name
  node_group_name = local.name
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = data.aws_subnets.private.ids
  ami_type        = "AL2023_ARM_64_STANDARD"
  instance_types  = [var.node_instance_type]
  disk_size       = 20

  scaling_config {
    desired_size = 1
    min_size     = 1
    max_size     = 1
  }

  depends_on = [aws_iam_role_policy_attachment.node]
}

resource "aws_eks_addon" "addons" {
  for_each     = toset(["vpc-cni", "kube-proxy", "coredns", "eks-pod-identity-agent"])
  cluster_name = aws_eks_cluster.main.name
  addon_name   = each.key
  depends_on   = [aws_eks_node_group.main]
}

# Images

resource "aws_ecr_repository" "repos" {
  for_each             = toset(["osrm", "simulator"])
  name                 = "${local.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true
  image_scanning_configuration {
    scan_on_push = true
  }
}

# Simulator identity (EKS Pod Identity): produce positions, read assignments
# and control commands, create topics, publish lifecycle events.

data "aws_iam_policy_document" "pods_assume" {
  statement {
    actions = ["sts:AssumeRole", "sts:TagSession"]
    principals {
      type        = "Service"
      identifiers = ["pods.eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "simulator" {
  name               = "${local.name}-simulator"
  assume_role_policy = data.aws_iam_policy_document.pods_assume.json
}

data "aws_iam_policy_document" "simulator" {
  statement {
    sid       = "MskConnect"
    actions   = ["kafka-cluster:Connect", "kafka-cluster:DescribeCluster"]
    resources = [local.msk_cluster]
  }
  statement {
    sid = "MskTopics"
    actions = [
      "kafka-cluster:CreateTopic", "kafka-cluster:DescribeTopic",
      "kafka-cluster:WriteData", "kafka-cluster:ReadData",
    ]
    resources = [local.msk_topic]
  }
  statement {
    sid = "MskGroups"
    actions = [
      "kafka-cluster:AlterGroup", "kafka-cluster:DescribeGroup",
    ]
    resources = [local.msk_group]
  }
  statement {
    sid       = "LifecycleEvents"
    actions   = ["events:PutEvents"]
    resources = [local.event_bus]
  }
}

resource "aws_iam_role_policy" "simulator" {
  name   = "simulator"
  role   = aws_iam_role.simulator.id
  policy = data.aws_iam_policy_document.simulator.json
}

resource "aws_eks_pod_identity_association" "simulator" {
  cluster_name    = aws_eks_cluster.main.name
  namespace       = "ride-dispatch"
  service_account = "simulator"
  role_arn        = aws_iam_role.simulator.arn
  depends_on      = [aws_eks_addon.addons]
}

# Network access from the cluster to MSK and Redis, and from the matching
# functions to the OSRM NodePort.

locals {
  cluster_sg = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
}

resource "aws_vpc_security_group_ingress_rule" "msk_from_nodes" {
  security_group_id            = data.aws_security_group.msk.id
  referenced_security_group_id = local.cluster_sg
  ip_protocol                  = "tcp"
  from_port                    = 9098
  to_port                      = 9098
  description                  = "Simulator pods"
}

resource "aws_vpc_security_group_ingress_rule" "redis_from_nodes" {
  security_group_id            = data.aws_security_group.redis.id
  referenced_security_group_id = local.cluster_sg
  ip_protocol                  = "tcp"
  from_port                    = 6379
  to_port                      = 6379
  description                  = "Measurement script run inside the cluster"
}

resource "aws_vpc_security_group_ingress_rule" "osrm_from_lambda" {
  security_group_id            = local.cluster_sg
  referenced_security_group_id = data.aws_security_group.lambda.id
  ip_protocol                  = "tcp"
  from_port                    = var.osrm_node_port
  to_port                      = var.osrm_node_port
  description                  = "Matching functions call OSRM through its NodePort"
}
