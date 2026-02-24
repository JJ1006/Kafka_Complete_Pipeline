# DLQ Recovery Runbook
# ─────────────────────────────────────────────────────────────────────────────
# Alert : DLQHasMessages (lagThreshold > 0)
# Impact: Messages failed Logstash processing; NOT indexed in Elasticsearch
# SLA   : Investigate within 30 minutes; process within 2 hours

## 1. Check DLQ message count

```bash
kubectl exec -n kafka kafka-0 -- \
  kafka-consumer-groups.sh \
    --bootstrap-server localhost:9092 \
    --group logstash-dlq-consumer \
    --describe
```

## 2. Inspect failed messages

```bash
kubectl exec -n kafka kafka-0 -- \
  kafka-console-consumer.sh \
    --bootstrap-server localhost:9092 \
    --topic credit.transactions.dlq \
    --from-beginning \
    --max-messages 10
```

Look for:
- Avro schema version mismatch → Schema Registry issue
- Missing required fields → upstream producer bug
- Encoding errors → character set problems

## 3. Schema mismatch recovery

```bash
# Check registered schema versions
curl http://schema-registry.kafka.svc.cluster.local:8081/subjects/credit.transactions.v1-value/versions

# If schema version drifted, re-register the correct schema:
curl -X POST \
  http://schema-registry.kafka.svc.cluster.local:8081/subjects/credit.transactions.v1-value/versions \
  -H 'Content-Type: application/vnd.schemaregistry.v1+json' \
  -d @infrastructure/schema/transaction-avro.json
```

## 4. Replay DLQ messages

After fixing the root cause, replay using Kafka Streams or a replay consumer:

```bash
kubectl apply -f infrastructure/k8s/dlq-replay-job.yaml
kubectl wait --for=condition=complete job/dlq-replay -n data-pipeline --timeout=10m
```

## 5. Verify Elasticsearch indexed messages

```bash
curl -s "http://elasticsearch.data-store.svc.cluster.local:9200/credit-transactions/_count" | jq .count
```

## Post-incident

- Root cause → fix producer or Logstash pipeline
- Consider auto-retry Logstash pipeline configuration
