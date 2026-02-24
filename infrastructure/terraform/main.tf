resource "kubernetes_namespace" "security" {
  metadata {
    name = "security"
  }
}

resource "kubernetes_namespace" "data_pipeline" {
  metadata {
    name = "data-pipeline"
  }
}

resource "kubernetes_namespace" "data_store" {
  metadata {
    name = "data-store"
  }
}

resource "kubernetes_namespace" "observability" {
  metadata {
    name = "observability"
  }
}

resource "kubernetes_namespace" "credit_platform" {
  metadata {
    name = "credit-platform"
  }
}

# Helm repositories are specified inline in helm_release resources

# Vault
resource "helm_release" "vault" {
  name       = "vault"
  repository = "https://helm.releases.hashicorp.com"
  chart      = "vault"
  namespace  = kubernetes_namespace.security.metadata[0].name
  version    = var.vault_chart_version

  values = [
    yamlencode({
      server = {
        dataStorage = {
          size = "1Gi"
        }
        dev = {
          enabled = true
        }
      }
    })
  ]

  depends_on = [kubernetes_namespace.security]
}

# Redis
resource "helm_release" "redis" {
  name       = "redis"
  repository = "https://charts.bitnami.com/bitnami"
  chart      = "redis"
  namespace  = kubernetes_namespace.data_store.metadata[0].name
  version    = var.redis_chart_version

  values = [
    yamlencode({
      auth = {
        enabled = false
      }
      master = {
        persistence = {
          enabled = false
        }
      }
      replica = {
        replicaCount = 0
      }
    })
  ]

  depends_on = [kubernetes_namespace.data_store]
}

# Kafka with KRaft mode (no Zookeeper - modern)
resource "helm_release" "kafka" {
  name       = "kafka"
  repository = "https://charts.bitnami.com/bitnami"
  chart      = "kafka"
  namespace  = kubernetes_namespace.data_pipeline.metadata[0].name
  version    = var.kafka_chart_version

  values = [
    yamlencode({
      replicaCount = var.kafka_replicas
      persistence = {
        enabled = false
      }
      kraft = {
        enabled = true  # Use KRaft mode (no Zookeeper needed)
      }
      controller = {
        enabled = true
        replicaCount = var.kafka_replicas
      }
      broker = {
        heapOpts = "-Xmx512m -Xms512m"
      }
      zookeeper = {
        enabled = false  # Disabled - using KRaft instead
      }
    })
  ]

  depends_on = [kubernetes_namespace.data_pipeline]
}

# Schema Registry
resource "helm_release" "schema_registry" {
  name       = "schema-registry"
  repository = "https://packages.confluent.io/helm"
  chart      = "cp-schema-registry"
  namespace  = kubernetes_namespace.data_pipeline.metadata[0].name
  version    = var.schema_registry_chart_version

  values = [
    yamlencode({
      kafka = {
        bootstrapServers = "kafka:9092"
      }
      resources = {
        limits = {
          memory = "512Mi"
          cpu    = "250m"
        }
        requests = {
          memory = "256Mi"
          cpu    = "100m"
        }
      }
    })
  ]

  depends_on = [helm_release.kafka]
}

# Logstash
resource "helm_release" "logstash" {
  name       = "logstash"
  repository = "https://charts.bitnami.com/bitnami"
  chart      = "logstash"
  namespace  = kubernetes_namespace.data_pipeline.metadata[0].name
  version    = var.logstash_chart_version

  values = [
    yamlencode({
      replicaCount = 2
      persistence = {
        enabled = false
      }
      logstashConfig = {
        logstash = {
          yml = ""
        }
      }
      logstashPipeline = {
        logstashfile = file("${path.module}/../logstash/pipeline/credit_transactions.conf")
      }
      env = {
        KAFKA_BOOTSTRAP_SERVERS = "kafka-0.kafka-headless.data-pipeline.svc.cluster.local:9092,kafka-1.kafka-headless.data-pipeline.svc.cluster.local:9092,kafka-2.kafka-headless.data-pipeline.svc.cluster.local:9092"
        ELASTICSEARCH_HOSTS     = "http://elasticsearch.data-store.svc.cluster.local:9200"
      }
      resources = {
        limits = {
          memory = "2Gi"
          cpu    = "1000m"
        }
        requests = {
          memory = "512Mi"
          cpu    = "300m"
        }
      }
    })
  ]

  depends_on = [helm_release.kafka, helm_release.schema_registry]
}

# Elasticsearch
resource "helm_release" "elasticsearch" {
  name       = "elasticsearch"
  repository = "https://charts.bitnami.com/bitnami"
  chart      = "elasticsearch"
  namespace  = kubernetes_namespace.data_store.metadata[0].name
  version    = var.elasticsearch_chart_version

  values = [
    yamlencode({
      replicaCount = var.elasticsearch_replicas
      persistence = {
        enabled = false
      }
      data = {
        replicaCount = 0
      }
      ingest = {
        enabled = false
      }
      resources = {
        limits = {
          memory = "1024Mi"
          cpu    = "500m"
        }
        requests = {
          memory = "512Mi"
          cpu    = "250m"
        }
      }
    })
  ]

  depends_on = [kubernetes_namespace.data_store]
}

# Kibana
resource "helm_release" "kibana" {
  name       = "kibana"
  repository = "https://charts.bitnami.com/bitnami"
  chart      = "kibana"
  namespace  = kubernetes_namespace.data_store.metadata[0].name
  version    = var.kibana_chart_version

  values = [
    yamlencode({
      elasticsearch = {
        hosts = ["elasticsearch"]
        port  = 9200
      }
      resources = {
        limits = {
          memory = "512Mi"
          cpu    = "250m"
        }
        requests = {
          memory = "256Mi"
          cpu    = "100m"
        }
      }
    })
  ]

  depends_on = [helm_release.elasticsearch]
}

# Prometheus Stack
resource "helm_release" "prometheus_stack" {
  name       = "prometheus"
  repository = "https://prometheus-community.github.io/helm-charts"
  chart      = "kube-prometheus-stack"
  namespace  = kubernetes_namespace.observability.metadata[0].name
  version    = var.prometheus_stack_chart_version

  values = [
    yamlencode({
      prometheus = {
        prometheusSpec = {
          storageSpec = {
            volumeClaimTemplate = {
              spec = {
                storageClassName = "standard"
                accessModes      = ["ReadWriteOnce"]
                resources = {
                  requests = {
                    storage = "2Gi"
                  }
                }
              }
            }
          }
          retention = "7d"
        }
      }
      grafana = {
        enabled = true
      }
    })
  ]

  depends_on = [kubernetes_namespace.observability]
}

# Jaeger
resource "helm_release" "jaeger" {
  name       = "jaeger"
  repository = "https://jaegertracing.github.io/helm-charts"
  chart      = "jaeger"
  namespace  = kubernetes_namespace.observability.metadata[0].name
  version    = var.jaeger_chart_version

  values = [
    yamlencode({
      persistence = {
        enabled = false
      }
      storage = {
        type = "memory"
      }
    })
  ]

  depends_on = [kubernetes_namespace.observability]
}

# OpenTelemetry Collector
resource "helm_release" "otel_collector" {
  name       = "otel-collector"
  repository = "https://open-telemetry.github.io/opentelemetry-helm-charts"
  chart      = "opentelemetry-collector"
  namespace  = kubernetes_namespace.observability.metadata[0].name
  version    = var.otel_collector_chart_version

  values = [
    yamlencode({
      mode = "daemonset"
      config = {
        receivers = {
          otlp = {
            protocols = {
              grpc = {
                endpoint = "0.0.0.0:4317"
              }
            }
          }
        }
        processors = {
          batch = {}
        }
        exporters = {
          jaeger = {
            endpoint = "jaeger-collector:14250"
          }
        }
        service = {
          pipelines = {
            traces = {
              receivers  = ["otlp"]
              processors = ["batch"]
              exporters  = ["jaeger"]
            }
          }
        }
      }
    })
  ]

  depends_on = [helm_release.jaeger]
}

# KEDA
resource "helm_release" "keda" {
  name       = "keda"
  repository = "https://kedacore.github.io/charts"
  chart      = "keda"
  namespace  = "keda"
  version    = var.keda_chart_version

  create_namespace = true

  values = [
    yamlencode({
      serviceAccount = {
        create = true
      }
    })
  ]
}
