output "kubernetes_cluster_info" {
  description = "Information about the Kubernetes cluster"
  value = {
    cluster_name    = "credit-platform"
    control_plane   = "https://127.0.0.1:50097"
    kubectl_context = "kind-credit-platform"
  }
}

output "namespaces" {
  description = "Kubernetes namespaces created"
  value = {
    security       = kubernetes_namespace.security.metadata[0].name
    data_pipeline  = kubernetes_namespace.data_pipeline.metadata[0].name
    data_store     = kubernetes_namespace.data_store.metadata[0].name
    observability  = kubernetes_namespace.observability.metadata[0].name
    credit_platform = kubernetes_namespace.credit_platform.metadata[0].name
  }
}

output "helm_releases" {
  description = "Deployed Helm releases"
  value = {
    vault               = helm_release.vault.status
    redis              = helm_release.redis.status
    kafka              = helm_release.kafka.status
    schema_registry    = helm_release.schema_registry.status
    elasticsearch      = helm_release.elasticsearch.status
    kibana             = helm_release.kibana.status
    prometheus_stack   = helm_release.prometheus_stack.status
    jaeger             = helm_release.jaeger.status
    otel_collector     = helm_release.otel_collector.status
    keda               = helm_release.keda.status
  }
}

output "port_forward_commands" {
  description = "Useful kubectl port-forward commands"
  value = "Useful commands:\n\n# Vault\nkubectl port-forward -n security svc/vault 8200:8200 &\n\n# Redis\nkubectl port-forward -n data-store svc/redis-master 6379:6379 &\n\n# Kafka\nkubectl port-forward -n data-pipeline svc/kafka 9092:9092 &\n\n# Schema Registry\nkubectl port-forward -n data-pipeline svc/schema-registry 8081:8081 &\n\n# Elasticsearch\nkubectl port-forward -n data-store svc/elasticsearch 9200:9200 &\n\n# Kibana\nkubectl port-forward -n data-store svc/kibana 5601:5601 &\n\n# Prometheus\nkubectl port-forward -n observability svc/prometheus-operated 9090:9090 &\n\n# Grafana\nkubectl port-forward -n observability svc/prometheus-grafana 3000:3000 &\n\n# Jaeger\nkubectl port-forward -n observability svc/jaeger-query 16686:16686 &"
}
