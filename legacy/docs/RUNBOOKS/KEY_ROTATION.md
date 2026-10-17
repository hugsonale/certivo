markdown# Key Rotation Runbook

## Overview

This runbook provides step-by-step procedures for rotating secrets and cryptographic keys in the Certivo platform.

## Rotation Schedule

| Secret Type | Frequency | Last Rotated | Next Due |
|-------------|-----------|--------------|----------|
| Database Passwords | Quarterly | 2025-01-01 | 2025-04-01 |
| API Keys | Monthly | 2025-01-15 | 2025-02-15 |
| Session Secrets | Quarterly | 2025-01-01 | 2025-04-01 |
| Encryption Keys | Annually | 2025-01-01 | 2026-01-01 |
| TLS Certificates | Before expiry | 2024-12-01 | 2025-12-01 |

---

## 1. Database Password Rotation

### Preparation

**Duration:** 30 minutes  
**Risk Level:** Medium  
**Requires Downtime:** No (zero-downtime rotation)

**Prerequisites:**
- [x] Maintenance window scheduled
- [x] Team notified
- [x] Backup completed
- [x] Rollback plan ready

### Procedure

**Step 1: Verify Current State**

```bash
# Test current database connection
psql -h db.certivo.internal -U certivo -d certivo -c "SELECT 1"

# Check active connections
psql -h db.certivo.internal -U certivo -d certivo -c \
  "SELECT count(*) FROM pg_stat_activity WHERE usename = 'certivo'"
```

**Step 2: Generate New Password**

```bash
# Generate secure password (32 characters)
NEW_PASSWORD=$(openssl rand -base64 32)

echo "New password generated (DO NOT LOG THIS)"
```

**Step 3: Update Database Password**

```sql
-- Connect as superuser
psql -h db.certivo.internal -U postgres

-- Update password
ALTER USER certivo WITH PASSWORD 'NEW_PASSWORD_HERE';

-- Verify
\password certivo
```

**Step 4: Update Vault**

```bash
# Store new password in Vault
vault kv put secret/production/database/password value="$NEW_PASSWORD"

# Verify
vault kv get secret/production/database/password
```

**Step 5: Rolling Update Services**

```bash
# Update services one at a time (zero-downtime)
kubectl rollout restart deployment/api-gateway
kubectl rollout status deployment/api-gateway

kubectl rollout restart deployment/verification-api
kubectl rollout status deployment/verification-api

kubectl rollout restart deployment/challenge-service
kubectl rollout status deployment/challenge-service
```

**Step 6: Verify Connectivity**

```bash
# Test from each service
kubectl exec -it deployment/api-gateway -- \
  psql -h db.certivo.internal -U certivo -d certivo -c "SELECT 1"
```

**Step 7: Update Documentation**

```bash
# Record rotation in audit log
echo "Database password rotated on $(date)" >> ROTATION_LOG.md
```

### Rollback

**If rotation fails:**

```sql
-- Revert to old password
ALTER USER certivo WITH PASSWORD 'OLD_PASSWORD_HERE';
```

```bash
# Restore old secret in Vault
vault kv put secret/production/database/password value="$OLD_PASSWORD"

# Restart services
kubectl rollout undo deployment/api-gateway
```

---

## 2. API Key Rotation

### Preparation

**Duration:** 15 minutes  
**Risk Level:** Low  
**Requires Downtime:** No (dual-key period)

### Procedure

**Step 1: Generate New API Key**

```bash
# Generate new key
NEW_API_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(64))")
```

**Step 2: Enable Dual-Key Period**

```bash
# Store new key
vault kv put secret/production/api/internal_new value="$NEW_API_KEY"

# Both old and new keys valid for 1 hour
```

**Step 3: Update External Services**

```bash
# Update external service configuration
curl -X POST https://external-service.com/api/keys \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"key": "'$NEW_API_KEY'"}'
```

**Step 4: Wait for Propagation**

```bash
# Wait 1 hour for all services to refresh keys
sleep 3600
```

**Step 5: Promote New Key**

```bash
# Move old key to archive
vault kv put secret/production/api/internal_old value="$OLD_API_KEY"

# Promote new key to current
vault kv put secret/production/api/internal value="$NEW_API_KEY"
```

**Step 6: Revoke Old Key**

```bash
# Remove old key from active rotation
vault kv delete secret/production/api/internal_old
```

---

## 3. Session Secret Rotation

### Preparation

**Duration:** 1 hour (session TTL)  
**Risk Level:** Medium  
**Requires Downtime:** No

### Procedure

**Step 1: Generate New Secret**

```bash
# Generate 256-bit secret
NEW_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
```

**Step 2: Enable Dual-Secret Validation**

```bash
# Store new secret
vault kv put secret/production/session/secret_new value="$NEW_SECRET"

# Both secrets validate for 1 hour
```

**Step 3: Deploy Updated Services**

```bash
# Update session validation to accept both secrets
kubectl set env deployment/api-gateway \
  SESSION_SECRET_NEW="$NEW_SECRET"

kubectl rollout status deployment/api-gateway
```

**Step 4: Wait for Session Expiry**

```bash
# Wait for all existing sessions to expire (1 hour TTL)
sleep 3600
```

**Step 5: Promote New Secret**

```bash
# Replace old secret
vault kv put secret/production/session/secret value="$NEW_SECRET"

# Remove dual-secret flag
kubectl set env deployment/api-gateway SESSION_SECRET_NEW-
```

---

## 4. Emergency Rotation

### When to Use

- ✅ Suspected credential compromise
- ✅ Security incident detected
- ✅ Employee termination (access removal)
- ✅ Third-party breach notification

### Emergency Procedure

**Step 1: Assess Scope**

```bash
# Identify affected secrets
AFFECTED_SECRETS="database_password api_keys session_secret"
```

**Step 2: Immediate Actions**

```bash
# Revoke compromised credentials immediately
vault kv delete secret/production/database/password
vault kv delete secret/production/api/internal
vault kv delete secret/production/session/secret
```

**Step 3: Emergency Rotation**

```bash
# Run automated emergency rotation
python scripts/emergency_rotate.py \
  --reason "Security incident SI-2025-001" \
  --secrets "$AFFECTED_SECRETS"
```

**Step 4: Verify System Health**

```bash
# Check all services healthy
kubectl get pods -n production

# Test critical paths
curl -f https://api.certivo.com/health
```

**Step 5: Post-Incident**

```bash
# Generate incident report
python scripts/generate_rotation_report.py \
  --incident SI-2025-001 \
  --output incident_report.pdf
```

---

## 5. Rotation Verification Checklist

After any rotation:

- [ ] New secret stored in Vault
- [ ] Old secret archived/deleted
- [ ] All services restarted successfully
- [ ] Health checks passing
- [ ] No error rate increase
- [ ] Audit log entry created
- [ ] Documentation updated
- [ ] Team notified
- [ ] Rotation scheduled for next cycle

---

## 6. Rollback Procedures

### Quick Rollback

```bash
# Restore from backup
vault kv rollback -version=1 secret/production/database/password

# Restart services
kubectl rollout undo deployment/api-gateway
```

### Full Rollback

```bash
# Restore entire Vault snapshot
vault operator raft snapshot restore backup-20250115.snap

# Restart all services
kubectl rollout restart deployment --all
```

---

## 7. Testing Rotation (Pre-Production)

### Rotation Drill

**Run quarterly to validate procedures**

```bash
# 1. Run in staging environment
export ENVIRONMENT=staging

# 2. Execute rotation
python scripts/rotate_all_secrets.py --dry-run

# 3. Verify
python scripts/verify_rotation.py

# 4. Document results
python scripts/generate_drill_report.py
```

---

## 8. Monitoring & Alerts

### Metrics to Monitor

```prometheus
# Failed rotation attempts
rate(key_rotation_failures_total[5m])

# Rotation duration
histogram_quantile(0.95, rate(key_rotation_duration_seconds[5m]))

# Secrets age
time() - secret_last_rotated_timestamp
```

### Alerts

```yaml
- alert: RotationOverdue
  expr: (time() - secret_last_rotated_timestamp) > 7776000  # 90 days
  severity: warning

- alert: RotationFailed
  expr: rate(key_rotation_failures_total[5m]) > 0
  severity: critical
```

---

## 9. Contacts & Escalation

**Primary:** Security Team (security@certivo.com)  
**Secondary:** DevOps Team (devops@certivo.com)  
**Emergency:** On-call Engineer (PagerDuty)

**Escalation Path:**
1. On-call Engineer (0-15 min)
2. Security Lead (15-30 min)
3. CTO (30+ min)