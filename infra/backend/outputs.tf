output "state_bucket" {
  description = "Bucket name for the backend.hcl file of the other stacks"
  value       = aws_s3_bucket.state.bucket
}

output "budget_name" {
  value = aws_budgets_budget.monthly.name
}
