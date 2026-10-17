output "cluster_name" {
  value = aws_eks_cluster.main.name
}

# Repository URLs contain the account ID: never printed into proof files.
output "ecr_osrm" {
  value     = aws_ecr_repository.repos["osrm"].repository_url
  sensitive = true
}

output "ecr_simulator" {
  value     = aws_ecr_repository.repos["simulator"].repository_url
  sensitive = true
}

output "node_group" {
  value = aws_eks_node_group.main.node_group_name
}
