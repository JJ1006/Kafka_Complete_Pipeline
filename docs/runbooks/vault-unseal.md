# Vault Unseal Runbook
# ─────────────────────────────────────────────────────────────────────────────
# Alert : VaultSealed (alertmanager alert from alerts.yaml)
# Impact: credit-api cannot fetch secrets; pods will fail to start
# SLA   : Resolve within 15 minutes of alert

## 1. Verify Vault is sealed

```bash
kubectl exec -n vault vault-0 -- vault status
# Sealed: true  ← confirm
```

## 2. Unseal with keys

You need 3 of the 5 unseal keys stored in 1Password → `vault/prod/unseal-keys`.

```bash
for KEY in <key1> <key2> <key3>; do
  kubectl exec -n vault vault-0 -- vault operator unseal "$KEY"
done
```

Confirm: `Sealed: false, Initialized: true`

## 3. Verify standby nodes (HA setup)

```bash
kubectl exec -n vault vault-1 -- vault status
kubectl exec -n vault vault-2 -- vault status
```

Repeat unseal for each if needed.

## 4. Verify credit-api can read secrets

```bash
kubectl exec -n credit-platform deploy/credit-api -- \
  wget -qO- http://vault.vault.svc.cluster.local:8200/v1/sys/health
```

## 5. Trigger rolling restart to pick up secrets

```bash
kubectl rollout restart deployment/credit-api -n credit-platform
kubectl rollout status deployment/credit-api -n credit-platform
```

## Post-incident

- File incident report in Jira with timeline and root cause.
- Review Vault HA auto-unseal configuration (Automate with AWS KMS).
