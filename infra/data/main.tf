# MSK (driver positions stream), ElastiCache Redis (proximity index),
# DynamoDB (rides, WebSocket connections), S3 archive and the Athena layer.

terraform {
  required_version = ">= 1.10"
  backend "s3" {
    key = "data/terraform.tfstate"
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
  # Deterministic, account-specific suffix without exposing the account ID.
  suffix         = substr(sha1(data.aws_caller_identity.current.account_id), 0, 8)
  archive_bucket = "ride-dispatch-archive-${local.suffix}"
}

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

# MSK: two kafka.t3.small brokers (one per AZ), IAM authentication only, TLS
# in transit, encryption at rest with the AWS managed key.

resource "aws_msk_configuration" "main" {
  name              = local.name
  kafka_versions    = [var.kafka_version]
  server_properties = <<-EOT
    auto.create.topics.enable=false
    default.replication.factor=2
    min.insync.replicas=1
    num.partitions=1
    log.retention.hours=24
  EOT
}

resource "aws_msk_cluster" "main" {
  cluster_name           = local.name
  kafka_version          = var.kafka_version
  number_of_broker_nodes = 2

  broker_node_group_info {
    instance_type   = "kafka.t3.small"
    client_subnets  = data.aws_subnets.private.ids
    security_groups = [data.aws_security_group.msk.id]
    storage_info {
      ebs_storage_info {
        volume_size = 10
      }
    }
  }

  client_authentication {
    unauthenticated = false
    sasl {
      iam = true
    }
  }

  encryption_info {
    encryption_in_transit {
      client_broker = "TLS"
      in_cluster    = true
    }
  }

  configuration_info {
    arn      = aws_msk_configuration.main.arn
    revision = aws_msk_configuration.main.latest_revision
  }
}

# ElastiCache Redis OSS: one cache.t4g.micro node, TLS and at-rest encryption.

resource "aws_elasticache_subnet_group" "main" {
  name       = local.name
  subnet_ids = data.aws_subnets.private.ids
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = local.name
  description                = "Driver proximity index"
  engine                     = "redis"
  engine_version             = "7.1"
  node_type                  = "cache.t4g.micro"
  num_cache_clusters         = 1
  port                       = 6379
  parameter_group_name       = "default.redis7"
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [data.aws_security_group.redis.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  automatic_failover_enabled = false
  snapshot_retention_limit   = 0
  apply_immediately          = true
}

# DynamoDB, on demand, encrypted at rest with the AWS owned key (default).

resource "aws_dynamodb_table" "rides" {
  name         = "${local.name}-rides"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "ride_id"
  attribute {
    name = "ride_id"
    type = "S"
  }
}

resource "aws_dynamodb_table" "connections" {
  name         = "${local.name}-connections"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "connection_id"
  attribute {
    name = "connection_id"
    type = "S"
  }
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }
}

# S3 archive: positions and completed rides from the archiver, the synthetic
# history, and Athena query results.

resource "aws_s3_bucket" "archive" {
  bucket        = local.archive_bucket
  force_destroy = true
}

resource "aws_s3_bucket_ownership_controls" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "archive" {
  bucket                  = aws_s3_bucket.archive.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

data "aws_iam_policy_document" "archive_tls_only" {
  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.archive.arn, "${aws_s3_bucket.archive.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "archive" {
  bucket     = aws_s3_bucket.archive.id
  policy     = data.aws_iam_policy_document.archive_tls_only.json
  depends_on = [aws_s3_bucket_public_access_block.archive]
}

# Athena: Glue tables with partition projection on dt, so new days are
# queryable without crawlers or MSCK REPAIR.

resource "aws_glue_catalog_database" "main" {
  name = "ride_dispatch"
}

locals {
  ride_columns = [
    ["ride_id", "string"], ["client_id", "string"], ["driver_id", "string"],
    ["requested_at", "string"], ["completed_at", "string"],
    ["pickup_lat", "double"], ["pickup_lng", "double"], ["pickup_zone", "string"],
    ["dropoff_lat", "double"], ["dropoff_lng", "double"],
    ["trip_distance_m", "int"], ["trip_duration_s", "int"],
    ["surge", "double"], ["price_kes", "int"],
  ]
  tables = {
    synthetic_ride_history = {
      prefix  = "synthetic_ride_history"
      columns = concat(local.ride_columns, [["synthetic", "boolean"]])
      comment = "SYNTHETIC: generated by services/simulator/simulator/history.py (seed 42), not real rides"
      hour    = false
    }
    rides = {
      prefix  = "rides"
      columns = local.ride_columns
      comment = "Rides completed in the live simulation, archived on TripCompleted"
      hour    = false
    }
    driver_positions = {
      prefix = "positions"
      columns = [["driver_id", "string"], ["lat", "double"], ["lng", "double"],
      ["status", "string"], ["ride_id", "string"], ["ts", "bigint"]]
      comment = "Simulated driver positions archived by the archiver consumer group"
      hour    = true
    }
  }
}

resource "aws_glue_catalog_table" "tables" {
  for_each      = local.tables
  name          = each.key
  database_name = aws_glue_catalog_database.main.name
  table_type    = "EXTERNAL_TABLE"
  description   = each.value.comment

  parameters = merge({
    "classification"              = "json"
    "projection.enabled"          = "true"
    "projection.dt.type"          = "date"
    "projection.dt.format"        = "yyyy-MM-dd"
    "projection.dt.range"         = "2026-01-01,NOW"
    "projection.dt.interval"      = "1"
    "projection.dt.interval.unit" = "DAYS"
    "storage.location.template"   = each.value.hour ? "s3://${local.archive_bucket}/${each.value.prefix}/dt=$${dt}/hour=$${hour}/" : "s3://${local.archive_bucket}/${each.value.prefix}/dt=$${dt}/"
    }, each.value.hour ? {
    "projection.hour.type"   = "integer"
    "projection.hour.range"  = "0,23"
    "projection.hour.digits" = "2"
  } : {})

  partition_keys {
    name = "dt"
    type = "string"
  }

  dynamic "partition_keys" {
    for_each = each.value.hour ? [1] : []
    content {
      name = "hour"
      type = "string"
    }
  }

  storage_descriptor {
    location      = "s3://${local.archive_bucket}/${each.value.prefix}/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"
    ser_de_info {
      serialization_library = "org.openx.data.jsonserde.JsonSerDe"
    }
    dynamic "columns" {
      for_each = each.value.columns
      content {
        name = columns.value[0]
        type = columns.value[1]
      }
    }
  }
}

resource "aws_athena_workgroup" "main" {
  name          = local.name
  force_destroy = true
  configuration {
    enforce_workgroup_configuration = true
    result_configuration {
      output_location = "s3://${local.archive_bucket}/athena-results/"
      encryption_configuration {
        encryption_option = "SSE_S3"
      }
    }
  }
}
