# Application layer: EventBridge bus and rules, the arm64 Lambda functions
# (one IAM role each), the two MSK event source mappings with separate consumer
# groups, and the WebSocket API.

terraform {
  required_version = ">= 1.10"
  backend "s3" {
    key = "app/terraform.tfstate"
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
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

data "aws_partition" "current" {}
data "aws_caller_identity" "current" {}

locals {
  name           = "ride-dispatch"
  partition      = data.aws_partition.current.partition
  account        = data.aws_caller_identity.current.account_id
  archive_bucket = "ride-dispatch-archive-${substr(sha1(local.account), 0, 8)}"
  dist           = "${path.module}/../../dist/lambda"
}

# Lookups of resources owned by the other stacks

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

data "aws_security_group" "lambda" {
  name   = "${local.name}-lambda"
  vpc_id = data.aws_vpc.main.id
}

data "aws_msk_cluster" "main" {
  cluster_name = local.name
}

data "aws_elasticache_replication_group" "redis" {
  replication_group_id = local.name
}

data "aws_dynamodb_table" "rides" {
  name = "${local.name}-rides"
}

data "aws_dynamodb_table" "connections" {
  name = "${local.name}-connections"
}

data "aws_s3_bucket" "archive" {
  bucket = local.archive_bucket
}

# The single EKS node exposes OSRM on a NodePort (see services/osrm/k8s.yaml).
data "aws_instances" "nodes" {
  instance_tags = {
    "eks:nodegroup-name" = local.name
  }
  instance_state_names = ["running"]
}

locals {
  msk_arn       = data.aws_msk_cluster.main.arn
  msk_uuid      = element(split("/", local.msk_arn), 2)
  msk_topic_arn = "arn:${local.partition}:kafka:${var.region}:${local.account}:topic/${local.name}/${local.msk_uuid}"
  msk_group_arn = "arn:${local.partition}:kafka:${var.region}:${local.account}:group/${local.name}/${local.msk_uuid}"
  osrm_url      = "http://${data.aws_instances.nodes.private_ips[0]}:${var.osrm_node_port}"
}

# Event bus

resource "aws_cloudwatch_event_bus" "main" {
  name = local.name
}

# Connect token for the WebSocket API, generated at deploy time and kept only
# in Terraform state and the function environment.
resource "random_password" "connect_token" {
  length  = 40
  special = false
}

# Functions

locals {
  lifecycle_types = ["RideSearching", "RideMatched", "RideNoDriver", "DriverEnRoute",
  "DriverArrived", "TripStarted", "TripCompleted"]

  functions = {
    matching-positions = {
      package = "matching", handler = "matching.handlers.positions_handler"
      vpc     = true, timeout = 30, memory = 256
    }
    matching-requests = {
      package = "matching", handler = "matching.handlers.ride_requested_handler"
      vpc     = true, timeout = 15, memory = 256
    }
    archiver-positions = {
      package = "archiver", handler = "archiver.handlers.positions_handler"
      vpc     = false, timeout = 30, memory = 256
    }
    archiver-trips = {
      package = "archiver", handler = "archiver.handlers.trip_completed_handler"
      vpc     = false, timeout = 10, memory = 256
    }
    lifecycle-update = {
      package = "lifecycle", handler = "lifecycle.handlers.lifecycle_handler"
      vpc     = false, timeout = 10, memory = 256
    }
    notifier = {
      package = "lifecycle", handler = "lifecycle.handlers.notify_handler"
      vpc     = false, timeout = 10, memory = 256
    }
    ws-connect = {
      package = "lifecycle", handler = "lifecycle.handlers.ws_connect_handler"
      vpc     = false, timeout = 10, memory = 256
    }
    ws-disconnect = {
      package = "lifecycle", handler = "lifecycle.handlers.ws_disconnect_handler"
      vpc     = false, timeout = 10, memory = 256
    }
    ws-request = {
      package = "lifecycle", handler = "lifecycle.handlers.ws_request_handler"
      vpc     = false, timeout = 10, memory = 256
    }
  }

  common_env = {
    EVENT_BUS_NAME = aws_cloudwatch_event_bus.main.name
  }

  env = {
    matching-positions = {
      REDIS_HOST       = data.aws_elasticache_replication_group.redis.primary_endpoint_address
      OSRM_URL         = local.osrm_url, KAFKA_BOOTSTRAP = data.aws_msk_cluster.main.bootstrap_brokers_sasl_iam
      KAFKA_IAM_REGION = var.region
    }
    matching-requests = {
      REDIS_HOST       = data.aws_elasticache_replication_group.redis.primary_endpoint_address
      OSRM_URL         = local.osrm_url, KAFKA_BOOTSTRAP = data.aws_msk_cluster.main.bootstrap_brokers_sasl_iam
      KAFKA_IAM_REGION = var.region
    }
    archiver-positions = { ARCHIVE_BUCKET = local.archive_bucket }
    archiver-trips     = { ARCHIVE_BUCKET = local.archive_bucket }
    lifecycle-update = {
      RIDES_TABLE = data.aws_dynamodb_table.rides.name, CONNECTIONS_TABLE = data.aws_dynamodb_table.connections.name
    }
    notifier = {
      RIDES_TABLE     = data.aws_dynamodb_table.rides.name, CONNECTIONS_TABLE = data.aws_dynamodb_table.connections.name
      WS_CALLBACK_URL = "https://${aws_apigatewayv2_api.ws.id}.execute-api.${var.region}.amazonaws.com/${aws_apigatewayv2_stage.demo.name}"
    }
    ws-connect = {
      RIDES_TABLE   = data.aws_dynamodb_table.rides.name, CONNECTIONS_TABLE = data.aws_dynamodb_table.connections.name
      CONNECT_TOKEN = random_password.connect_token.result
    }
    ws-disconnect = {
      RIDES_TABLE = data.aws_dynamodb_table.rides.name, CONNECTIONS_TABLE = data.aws_dynamodb_table.connections.name
    }
    ws-request = {
      RIDES_TABLE = data.aws_dynamodb_table.rides.name, CONNECTIONS_TABLE = data.aws_dynamodb_table.connections.name
    }
  }
}

resource "aws_cloudwatch_log_group" "fn" {
  for_each          = local.functions
  name              = "/aws/lambda/${local.name}-${each.key}"
  retention_in_days = 1
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "fn" {
  for_each           = local.functions
  name               = "${local.name}-${each.key}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_lambda_function" "fn" {
  for_each         = local.functions
  function_name    = "${local.name}-${each.key}"
  role             = aws_iam_role.fn[each.key].arn
  runtime          = "python3.13"
  architectures    = ["arm64"]
  handler          = each.value.handler
  filename         = "${local.dist}/${each.value.package}.zip"
  source_code_hash = filebase64sha256("${local.dist}/${each.value.package}.zip")
  timeout          = each.value.timeout
  memory_size      = each.value.memory

  environment {
    variables = merge(local.common_env, local.env[each.key])
  }

  dynamic "vpc_config" {
    for_each = each.value.vpc ? [1] : []
    content {
      subnet_ids         = data.aws_subnets.private.ids
      security_group_ids = [data.aws_security_group.lambda.id]
    }
  }

  depends_on = [aws_cloudwatch_log_group.fn, aws_iam_role_policy.fn]
}

# Least-privilege policies, one per function

locals {
  bus_arn         = aws_cloudwatch_event_bus.main.arn
  ws_manage_arn   = "${aws_apigatewayv2_api.ws.execution_arn}/${aws_apigatewayv2_stage.demo.name}/POST/@connections/*"
  positions_topic = "${local.msk_topic_arn}/driver-positions"

  # VPC-attached functions and MSK event source mappings create ENIs with the
  # function role. These EC2 actions do not support resource-level scoping on
  # create and describe, hence "*" (see docs/DECISIONS.md).
  esm_network = {
    sid = "VpcNetworkInterfaces"
    actions = ["ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DeleteNetworkInterface",
      "ec2:AssignPrivateIpAddresses", "ec2:UnassignPrivateIpAddresses",
    "ec2:DescribeVpcs", "ec2:DescribeSubnets", "ec2:DescribeSecurityGroups"]
    resources = ["*"]
  }
  msk_describe = {
    sid       = "MskDescribe"
    actions   = ["kafka:DescribeClusterV2", "kafka:GetBootstrapBrokers"]
    resources = [local.msk_arn]
  }

  statements = {
    matching-positions = [
      local.esm_network, local.msk_describe,
      { sid = "MskConnect", actions = ["kafka-cluster:Connect"], resources = [local.msk_arn] },
      { sid = "MskRead", actions = ["kafka-cluster:DescribeTopic", "kafka-cluster:ReadData"], resources = [local.positions_topic] },
      { sid = "MskGroup", actions = ["kafka-cluster:AlterGroup", "kafka-cluster:DescribeGroup"], resources = ["${local.msk_group_arn}/matching"] },
      { sid = "Snapshot", actions = ["events:PutEvents"], resources = [local.bus_arn] },
    ]
    matching-requests = [
      local.esm_network,
      { sid = "MskConnect", actions = ["kafka-cluster:Connect"], resources = [local.msk_arn] },
      { sid = "MskWrite", actions = ["kafka-cluster:DescribeTopic", "kafka-cluster:WriteData"], resources = ["${local.msk_topic_arn}/ride-assignments"] },
      { sid = "Lifecycle", actions = ["events:PutEvents"], resources = [local.bus_arn] },
    ]
    archiver-positions = [
      local.esm_network, local.msk_describe,
      { sid = "MskConnect", actions = ["kafka-cluster:Connect"], resources = [local.msk_arn] },
      { sid = "MskRead", actions = ["kafka-cluster:DescribeTopic", "kafka-cluster:ReadData"], resources = [local.positions_topic] },
      { sid = "MskGroup", actions = ["kafka-cluster:AlterGroup", "kafka-cluster:DescribeGroup"], resources = ["${local.msk_group_arn}/archiver"] },
      { sid = "Archive", actions = ["s3:PutObject"], resources = ["${data.aws_s3_bucket.archive.arn}/positions/*"] },
    ]
    archiver-trips = [
      { sid = "Archive", actions = ["s3:PutObject"], resources = ["${data.aws_s3_bucket.archive.arn}/rides/*"] },
    ]
    lifecycle-update = [
      { sid = "Rides", actions = ["dynamodb:UpdateItem"], resources = [data.aws_dynamodb_table.rides.arn] },
    ]
    notifier = [
      { sid = "Connections", actions = ["dynamodb:Scan", "dynamodb:DeleteItem"], resources = [data.aws_dynamodb_table.connections.arn] },
      { sid = "Push", actions = ["execute-api:ManageConnections"], resources = [local.ws_manage_arn] },
    ]
    ws-connect = [
      { sid = "Connections", actions = ["dynamodb:PutItem"], resources = [data.aws_dynamodb_table.connections.arn] },
    ]
    ws-disconnect = [
      { sid = "Connections", actions = ["dynamodb:DeleteItem"], resources = [data.aws_dynamodb_table.connections.arn] },
    ]
    ws-request = [
      { sid = "Rides", actions = ["dynamodb:PutItem"], resources = [data.aws_dynamodb_table.rides.arn] },
      { sid = "Lifecycle", actions = ["events:PutEvents"], resources = [local.bus_arn] },
    ]
  }
}

data "aws_iam_policy_document" "fn" {
  for_each = local.functions

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.fn[each.key].arn}:*"]
  }

  dynamic "statement" {
    for_each = local.statements[each.key]
    content {
      sid       = statement.value.sid
      actions   = statement.value.actions
      resources = statement.value.resources
    }
  }
}

resource "aws_iam_role_policy" "fn" {
  for_each = local.functions
  name     = "least-privilege"
  role     = aws_iam_role.fn[each.key].id
  policy   = data.aws_iam_policy_document.fn[each.key].json
}

# Two consumer groups on the same topic: independent offsets and lag.

resource "aws_lambda_event_source_mapping" "positions" {
  for_each = {
    matching = "matching-positions"
    archiver = "archiver-positions"
  }
  event_source_arn                   = local.msk_arn
  function_name                      = aws_lambda_function.fn[each.value].arn
  topics                             = ["driver-positions"]
  starting_position                  = "LATEST"
  batch_size                         = 500
  maximum_batching_window_in_seconds = each.key == "matching" ? 1 : 10

  amazon_managed_kafka_event_source_config {
    consumer_group_id = each.key
  }

  depends_on = [aws_iam_role_policy.fn]
}

# EventBridge rules

locals {
  rules = {
    ride-requested = { types = ["RideRequested"], target = "matching-requests" }
    lifecycle      = { types = local.lifecycle_types, target = "lifecycle-update" }
    notify         = { types = concat(["RideRequested", "PositionsSnapshot"], local.lifecycle_types), target = "notifier" }
    trip-completed = { types = ["TripCompleted"], target = "archiver-trips" }
  }
}

resource "aws_cloudwatch_event_rule" "rules" {
  for_each       = local.rules
  name           = "${local.name}-${each.key}"
  event_bus_name = aws_cloudwatch_event_bus.main.name
  event_pattern = jsonencode({
    source        = ["ride-dispatch"]
    "detail-type" = each.value.types
  })
}

resource "aws_cloudwatch_event_target" "rules" {
  for_each       = local.rules
  rule           = aws_cloudwatch_event_rule.rules[each.key].name
  event_bus_name = aws_cloudwatch_event_bus.main.name
  arn            = aws_lambda_function.fn[each.value.target].arn
  retry_policy {
    maximum_event_age_in_seconds = 300
    maximum_retry_attempts       = 2
  }
}

resource "aws_lambda_permission" "events" {
  for_each      = local.rules
  statement_id  = "events-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn[each.value.target].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.rules[each.key].arn
}

# WebSocket API

resource "aws_apigatewayv2_api" "ws" {
  name                       = local.name
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"
}

locals {
  routes = {
    "$connect"    = "ws-connect"
    "$disconnect" = "ws-disconnect"
    "requestRide" = "ws-request"
  }
}

resource "aws_apigatewayv2_integration" "ws" {
  for_each           = local.routes
  api_id             = aws_apigatewayv2_api.ws.id
  integration_type   = "AWS_PROXY"
  integration_uri    = aws_lambda_function.fn[each.value].invoke_arn
  integration_method = "POST"
}

resource "aws_apigatewayv2_route" "ws" {
  for_each  = local.routes
  api_id    = aws_apigatewayv2_api.ws.id
  route_key = each.key
  target    = "integrations/${aws_apigatewayv2_integration.ws[each.key].id}"
  # requestRide returns the Lambda body (requestAck) to the caller.
  route_response_selection_expression = each.key == "requestRide" ? "$default" : null
}

resource "aws_apigatewayv2_route_response" "request" {
  api_id             = aws_apigatewayv2_api.ws.id
  route_id           = aws_apigatewayv2_route.ws["requestRide"].id
  route_response_key = "$default"
}

resource "aws_cloudwatch_log_group" "ws_access" {
  name              = "/aws/apigateway/${local.name}-ws"
  retention_in_days = 1
}

resource "aws_apigatewayv2_stage" "demo" {
  api_id      = aws_apigatewayv2_api.ws.id
  name        = "demo"
  auto_deploy = true

  default_route_settings {
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }
}

resource "aws_lambda_permission" "ws" {
  for_each      = local.routes
  statement_id  = "apigw-${trimprefix(each.key, "$")}"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.fn[each.value].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.ws.execution_arn}/*/${each.key}"
}
