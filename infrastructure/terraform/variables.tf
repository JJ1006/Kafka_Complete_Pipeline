variable "kafka_chart_version" {
  type    = string
  default = "26.4.1"
}

variable "schema_registry_chart_version" {
  type    = string
  default = "0.7.0"
}

variable "elasticsearch_chart_version" {
  type    = string
  default = "19.9.5"
}

variable "kibana_chart_version" {
  type    = string
  default = "10.5.4"
}

variable "logstash_chart_version" {
  type    = string
  default = "5.5.2"
}

variable "redis_chart_version" {
  type    = string
  default = "18.4.0"
}

variable "prometheus_stack_chart_version" {
  type    = string
  default = "55.12.0"
}

variable "jaeger_chart_version" {
  type    = string
  default = "0.71.7"
}

variable "otel_collector_chart_version" {
  type    = string
  default = "0.83.0"
}

variable "keda_chart_version" {
  type    = string
  default = "2.13.0"
}

variable "vault_chart_version" {
  type    = string
  default = "0.27.0"
}

variable "kafka_replicas" {
  type    = number
  default = 1
}

variable "elasticsearch_replicas" {
  type    = number
  default = 1
}
