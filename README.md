<div align="center">

# 🏦 Credit Transaction Platform

**A production-grade, cloud-native pipeline for real-time credit transaction ingestion, processing, and analytics.**

[![CI](https://github.com/JJ1006/Kafka_Complete_Pipeline/actions/workflows/ci.yaml/badge.svg)](https://github.com/JJ1006/Kafka_Complete_Pipeline/actions/workflows/ci.yaml)
[![CD](https://github.com/JJ1006/Kafka_Complete_Pipeline/actions/workflows/cd.yaml/badge.svg)](https://github.com/JJ1006/Kafka_Complete_Pipeline/actions/workflows/cd.yaml)
[![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/License-MIT-blue)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Tests](https://img.shields.io/badge/tests-26%20passed-22c55e)](https://github.com/JJ1006/Kafka_Complete_Pipeline/actions)

</div>

---

## ✨ Overview

The **Credit Transaction Platform** ingests, processes, and serves credit transaction data at scale. Built on an event-driven architecture, it handles **high-throughput ingest** (Kafka), **fast full-text search** (Elasticsearch), **low-latency caching** (Redis), and **enterprise observability** (OpenTelemetry + Prometheus + Grafana).

### 🎯 Key Capabilities

| Capability | Details |
|---|---|
| **Ingest** | `POST /transactions` → Kafka → Logstash → Elasticsearch |
| **Deduplication** | Redis-backed composite-key dedup (idempotent, 24h window) |
| **Search** | Paginated list, date-range queries, composite-key lookup |
| **Streaming Export** | CSV/JSONL download via async generator (never buffered) |
| **Observability** | OpenTelemetry traces, Prometheus metrics, structured JSON logs |
| **Security** | Vault-managed secrets, network policies, Trivy image scans |
| **Scalability** | KEDA-driven Logstash autoscaling on Kafka consumer lag |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Credit Transaction Platform                   │
│                                                                       │
│  ┌──────────┐    POST /transactions    ┌────────────────────────┐   │
│  │  Client  │ ─────────────────────▶  │    FastAPI (credit-api) │   │
│  │  / SPA   │                         │    Port 8000            │   │
│  └──────────┘                         └────────┬───────┬────────┘   │
│                                                │       │             │
│                                         Produce│  Check│Dedup        │
│                                                ▼       ▼             │
│                              ┌──────────────────┐  ┌──────────┐    │
│                              │  Apache Kafka     │  │  Redis   │    │
│                              │  credit.txn.v1   │  │  (dedup) │    │
│                              └────────┬─────────┘  └──────────┘    │
│                                       │ Consume                      │
│                                       ▼                              │
│                             ┌──────────────────┐                    │
│                             │  Logstash         │ ← KEDA autoscale  │
│                             │  (Avro → JSON)    │   on lag          │
│                             └────────┬──────────┘                   │
│                                      │ Index                         │
│                                      ▼                               │
│                          ┌─────────────────────┐                    │
│                          │   Elasticsearch      │                    │
│                          │   credit-transactions│                    │
│                          └────────┬────────────┘                    │
│                                   │                                  │
│            ┌──────────────────────┼──────────────────────┐         │
│            ▼                      ▼                       ▼         │
│       GET /tx/{id}      GET /tx/range        GET /tx/download       │
│       (single lookup)   (date range)         (CSV / JSONL)          │
│                                                                       │
│  Observability: Prometheus → Grafana · OpenTelemetry → Jaeger       │
│  Secrets: HashiCorp Vault (dynamic credentials)                      │
│  CI/CD: GitHub Actions → GHCR → ArgoCD (GitOps)                    │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🚀 Quick Start

### Prerequisites

| Tool | Version |
|---|---|
| Python | 3.12+ |
| Docker & Docker Compose | 24+ |
| kubectl | 1.29+ (for k8s deploy) |
| kind | 0.22+ (for local cluster) |

### 1. Clone & install dependencies

```bash
git clone https://github.com/JJ1006/Kafka_Complete_Pipeline.git
cd Kafka_Complete_Pipeline

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,test]"
```

### 2. Run locally with Docker Compose

```bash
# Start all services (Kafka, Zookeeper, Redis, Elasticsearch, Logstash, Grafana)
docker-compose up -d

# Start the API (after services are healthy)
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000
```

API available at **http://localhost:8000** · Docs at **http://localhost:8000/docs**
SPA available at **http://localhost:8000/ui**

### 3. Ingest your first transaction

```bash
curl -X POST http://localhost:8000/transactions \
  -H "Content-Type: application/json" \
  -H "X-API-Key: dev-api-key" \
  -d '{
    "application_number": "APP001",
    "request_id":         "REQ001",
    "transunion_score":   720,
    "loan_amount":        50000,
    "tenure_months":      60,
    "interest_rate_apr":  8.5,
    "employment_type":    "Salaried",
    "product_type":       "PersonalLoan"
  }'
```

Expected response:
```json
{
  "composite_key": "APP001:REQ001",
  "ingested_at": "2025-02-23T21:00:00Z",
  "correlation_id": "..."
}
```

---

## 📁 Project Structure

```
Kafka_Complete_Pipeline/
├── src/
│   ├── api/
│   │   ├── core/           # Config, logging, metrics, telemetry
│   │   ├── models/         # Pydantic request/response schemas
│   │   ├── routers/        # FastAPI route handlers (transactions, query, health)
│   │   └── services/       # Business logic (Kafka, Redis, Elasticsearch, dedup)
│   └── web/
│       ├── static/         # Vue 3 SPA (index.html — CDN ESM build)
│       ├── Dockerfile      # Multi-stage Nginx container
│       └── nginx.conf      # Reverse proxy + SPA fallback
├── tests/
│   ├── unit/               # 26 passing unit tests (httpx ASGITransport)
│   ├── integration/        # 7 integration scenarios (requires running services)
│   ├── load/               # k6 load test (3 scenarios, p95 thresholds)
│   └── fixtures/           # Seed transaction data (10 records)
├── infrastructure/
│   ├── grafana/            # 10-panel Grafana dashboard JSON
│   ├── prometheus/         # 7 Alertmanager rules
│   ├── logstash/           # Pipeline config + Avro schema
│   ├── helm/               # Helm chart (credit-api)
│   ├── argocd/             # ArgoCD Application manifest
│   └── k8s/
│       ├── keda-scaledobject.yaml          # Logstash autoscaler
│       └── network-policies/              # Default-deny + allow rules
├── docs/
│   └── runbooks/           # Vault unseal, DLQ recovery
├── .github/
│   ├── workflows/          # ci.yaml, cd.yaml
│   └── dependabot.yaml     # Automated dependency updates
├── docker-compose.yaml
├── Dockerfile
└── pyproject.toml
```

---

## 🔌 API Reference

### Ingest

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/transactions` | Ingest a transaction → Kafka |
| `GET` | `/health` | Liveness + dependency health check |

### Query

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/transactions/{appNum}/{reqId}` | Get single transaction (Redis cache → ES) |
| `GET` | `/transactions?application_number=X` | Paginated list for an application |
| `GET` | `/transactions/range` | Date-range query with optional filters |
| `GET` | `/transactions/download` | Streaming CSV/JSONL export |

**Authentication**: all endpoints require `X-API-Key` header.

Full interactive docs: **http://localhost:8000/docs** (Swagger UI)

---

## 🧪 Testing

```bash
# Run all unit tests (26 tests, ~1.2s)
pytest tests/unit/ -v

# Run with coverage report
pytest tests/unit/ --cov=src --cov-report=term-missing --cov-fail-under=80

# Run integration tests (requires running services)
export CREDIT_API_URL=http://localhost:8000
export CREDIT_API_KEY=dev-api-key
pytest tests/integration/ -v -m integration

# Run k6 load test
k6 run tests/load/load_test.js \
  --env API_URL=http://localhost:8000 \
  --env API_KEY=dev-api-key
```

### Test Coverage Summary

| Suite | Tests | Status |
|---|---|---|
| Unit — Ingest | 11 | ✅ All pass |
| Unit — Query | 15 | ✅ All pass |
| Integration | 7 | Requires services |
| Load (k6) | 3 scenarios | p95 \< 500ms ingest, \< 250ms query |

---

## 📊 Observability

### Metrics (Prometheus)

| Metric | Description |
|---|---|
| `http_request_duration_seconds` | API latency histogram (p50/p95/p99) |
| `ingest_total` | Ingest count by status |
| `kafka_produce_total` | Kafka produce success/failure |
| `redis_cache_hits_total` | Cache hit counter |
| `es_query_duration_seconds` | Elasticsearch query latency |

### Grafana Dashboard

Import `infrastructure/grafana/credit-platform-dashboard.json` into Grafana. The dashboard includes 10 panels:

1. API Request Rate (req/s)
2. API Latency p50/p95/p99
3. Kafka Produce Rate
4. Kafka Consumer Lag
5. Elasticsearch Search Latency
6. Elasticsearch Indexing Rate
7. Redis Cache Hit Rate
8. Duplicates Rejected (dedup)
9. DLQ Message Count
10. Pod CPU & Memory Utilization

### Alertmanager Rules

See `infrastructure/prometheus/alerts.yaml` for 7 pre-configured alerts:
- `HighAPIErrorRate` — error rate > 5%
- `HighAPILatency` — p95 > 500ms
- `KafkaConsumerLag` — lag > 5000
- `DLQHasMessages` — any DLQ messages
- `ElasticsearchDown` — ES unreachable
- `RedisDown` — Redis unreachable
- `VaultSealed` — Vault sealed

---

## 🛡️ Security

- **Secrets**: HashiCorp Vault (dynamic credentials — no secrets in env vars)
- **Network**: Kubernetes NetworkPolicy default-deny with targeted allow rules
- **Images**: Trivy vulnerability scanning on every CI build (CRITICAL/HIGH block merge)
- **Dependencies**: Dependabot weekly updates (semver-major blocked)
- **Scanning**: `detect-secrets` pre-commit hook on every commit

---

## 🚢 Deployment

### Kubernetes (ArgoCD GitOps)

```bash
# Apply ArgoCD Application — it will auto-sync from this repo
kubectl apply -f infrastructure/argocd/credit-api-app.yaml

# Watch sync status
argocd app get credit-api
```

### CI/CD Pipeline

```
git push main
    │
    ▼
[CI] Lint + Type Check
    │
    ▼
[CI] Unit Tests (coverage ≥ 80%)
    │
    ▼
[CI] Docker Build + Trivy Scan
    │
    ▼
[CD] Push to GHCR (linux/amd64 + linux/arm64)
    │
    ▼
[CD] Update Helm values.yaml (new image tag)
    │
    ▼
[ArgoCD] Detects values.yaml change → Auto-deploy
```

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `KAFKA_BOOTSTRAP_SERVERS` | Kafka broker address | `kafka:9092` |
| `REDIS_URL` | Redis connection URL | `redis://redis:6379` |
| `ELASTICSEARCH_URL` | ES cluster URL | `http://elasticsearch:9200` |
| `VAULT_ADDR` | Vault server URL | `http://vault:8200` |
| `API_KEY_SECRET_PATH` | Vault path for API key | `secret/credit-api/api-key` |

---

## 📚 Runbooks

| Scenario | Runbook |
|---|---|
| Vault sealed | [docs/runbooks/vault-unseal.md](docs/runbooks/vault-unseal.md) |
| DLQ messages | [docs/runbooks/dlq-recovery.md](docs/runbooks/dlq-recovery.md) |

---

## 🤝 Contributing

1. **Fork** the repo and create a branch: `git checkout -b feature/my-feature`
2. **Commit** your changes (pre-commit hooks run automatically)
3. **Open a PR** — CI must pass (lint + tests + Trivy) before merge
4. **One reviewer approval** required (branch protection enforced)

### Development Setup

```bash
# Install pre-commit hooks
pip install pre-commit && pre-commit install

# Run all hooks manually
pre-commit run --all-files

# Type check
mypy src/

# Format
black src/ tests/ && ruff check src/ tests/ --fix
```

---

## 📄 License

MIT © 2025 [JJ1006](https://github.com/JJ1006)
