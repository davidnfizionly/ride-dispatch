# Endpoints are marked sensitive so they are never printed in logs or proof.

output "msk_cluster_name" {
  value = aws_msk_cluster.main.cluster_name
}

output "msk_bootstrap_iam" {
  value     = aws_msk_cluster.main.bootstrap_brokers_sasl_iam
  sensitive = true
}

output "redis_host" {
  value     = aws_elasticache_replication_group.redis.primary_endpoint_address
  sensitive = true
}

output "archive_bucket" {
  value     = aws_s3_bucket.archive.bucket
  sensitive = true
}

output "rides_table" {
  value = aws_dynamodb_table.rides.name
}

output "connections_table" {
  value = aws_dynamodb_table.connections.name
}

output "athena_workgroup" {
  value = aws_athena_workgroup.main.name
}
