variable "region" {
  type    = string
  default = "us-east-1"
}

variable "eks_version" {
  type    = string
  default = "1.36"
}

variable "node_instance_type" {
  type    = string
  default = "t4g.medium"
}

variable "osrm_node_port" {
  type    = number
  default = 30500
}

# Set in an untracked terraform.tfvars: the operator's public address as /32.
variable "admin_cidrs" {
  type = list(string)
}
