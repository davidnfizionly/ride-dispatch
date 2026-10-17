variable "region" {
  type    = string
  default = "us-east-1"
}

# ZooKeeper mode: kafka.t3.small is not available for KRaft clusters.
variable "kafka_version" {
  type    = string
  default = "3.9.x"
}
