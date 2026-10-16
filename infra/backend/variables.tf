variable "region" {
  description = "AWS region for the whole project"
  type        = string
  default     = "us-east-1"
}

variable "monthly_budget_usd" {
  description = "Monthly cost budget, credits and refunds excluded"
  type        = string
  default     = "25"
}
