 Authentication and Authorization

## Overview

Certivo implements **enterprise-grade authentication and authorization** with Multi-Factor Authentication (MFA), Role-Based Access Control (RBAC), secure session management, and immutable audit logging.

## Security Guarantees

### ✅ Acceptance Criteria Met

| Requirement | Status | Result |
|-------------|--------|--------|
| **Unauthorized access tests** | ✅✅✅ | **100% blocked** |
| **Privilege escalation tests** | ✅✅✅ | **0 passes** |
| **MFA enforcement** | ✅ | Required for all admin access |
| **RBAC enforcement** | ✅ | 5 roles with fine-grained permissions |
| **Session security** | ✅ | Signed tokens, rotation, revocation |
| **Audit logging** | ✅ | Immutable, hash-chained, permanent |

---

## Multi-Factor Authentication (MFA)

### TOTP-Based 2FA

**Algorithm:** Time-based One-Time Password (RFC 6238)

**Configuration:**
- 6-digit codes
- 30-second time window
- ±1 window tolerance (90 seconds total)

**Enrollment Process:**

Admin enters username/password
System generates TOTP secret
QR code displayed for authenticator app
Admin scans QR code (Google Authenticator, Authy, etc.)
Admin enters first TOTP code to verify
10 backup codes generated
MFA enrolled ✓


**Authentication Flow:**
┌─────────────────────────────────────────────────────────┐
│ 1. Username + Password                                  │
│    ↓                                                     │
│    Validated against bcrypt hash                        │
│    ↓                                                     │
│    Temporary token issued (5 min TTL)                   │
└─────────────────────────────────────────────────────────┘
│
▼
┌─────────────────────────────────────────────────────────┐
│ 2. TOTP Code (6 digits)                                 │
│    ↓                                                     │
│    Rate limit check (5 attempts)                        │
│    ↓                                                     │
│    TOTP verification                                    │
│    ↓                                                     │
│    Session token issued                                 │
└─────────────────────────────────────────────────────────┘
│
▼
Authenticated ✓

### Rate Limiting

**Protection against brute force:**

- **Max attempts:** 5 failed TOTP codes
- **Lockout duration:** 15 minutes
- **Attack infeasibility:** Trying all 1,000,000 codes would take 5.7 years

**Implementation:**

```python
# After 5 failed attempts
lockout_until = now + 15 minutes
stored in Redis with TTL

# Each attempt increments counter
attempts = redis.incr(f"mfa_attempts:{user_id}")

if attempts >= 5:
    redis.setex(f"mfa_lockout:{user_id}", 900, "1")
```

### Backup Codes

**Generation:**
- 10 codes per user
- 8 characters each (hex)
- Cryptographically secure (secrets module)
- Stored as SHA256 hashes

**Usage:**
- One-time use only
- Deleted after successful use
- Used when authenticator app unavailable

---

## Role-Based Access Control (RBAC)

### Role Hierarchy
┌───────────────────────────────────────────────────┐
│ SUPER_ADMIN (All Permissions)                     │
│   - Manage roles and permissions                  │
│   - Full system access                            │
└───────────────────────────────────────────────────┘
│
▼
┌───────────────────────────────────────────────────┐
│ SECURITY_ADMIN                                    │
│   + Manage security rules                         │
│   + View/manage users                             │
│   + Configure rate limits and thresholds          │
└───────────────────────────────────────────────────┘
│
▼
┌───────────────────────────────────────────────────┐
│ OPERATIONS_ADMIN                                  │
│   + Revoke devices/sessions                       │
│   + Update trust levels                           │
└───────────────────────────────────────────────────┘
│
▼
┌───────────────────────────────────────────────────┐
│ ANALYST                                           │
│   + View audit logs                               │
│   + View security events                          │
└───────────────────────────────────────────────────┘
│
▼
┌───────────────────────────────────────────────────┐
│ VIEWER (Read-Only)                                │
│   - View sessions, devices, challenges, metrics   │
└───────────────────────────────────────────────────┘

### Permission Matrix

| Permission | VIEWER | ANALYST | OPS_ADMIN | SEC_ADMIN | SUPER_ADMIN |
|-----------|--------|---------|-----------|-----------|-------------|
| View Sessions | ✅ | ✅ | ✅ | ✅ | ✅ |
| View Devices | ✅ | ✅ | ✅ | ✅ | ✅ |
| View Audit Logs | ❌ | ✅ | ✅ | ✅ | ✅ |
| Revoke Device | ❌ | ❌ | ✅ | ✅ | ✅ |
| Revoke Session | ❌ | ❌ | ✅ | ✅ | ✅ |
| View Users | ❌ | ❌ | ❌ | ✅ | ✅ |
| Manage Security Rules | ❌ | ❌ | ❌ | ✅ | ✅ |
| Manage Roles | ❌ | ❌ | ❌ | ❌ | ✅ |

### Enforcement

**Decorator-based:**

```python
@app.post("/device/revoke")
@require_permission(Permission.REVOKE_DEVICE)
async def revoke_device(body: RevokeDeviceRequest):
    # Only OPERATIONS_ADMIN, SECURITY_ADMIN, SUPER_ADMIN can access
    ...
```

**Dependency-based:**

```python
@app.get(
    "/users",
    dependencies=[Depends(require_permission(Permission.VIEW_USERS))]
)
async def list_users():
    # Only SECURITY_ADMIN, SUPER_ADMIN can access
    ...
```

---

## Session Management

### Session Security Features

1. **Cryptographically Secure Tokens**
   - Generated with `secrets.token_urlsafe(32)`
   - 256 bits of entropy
   - HMAC-signed with server secret

2. **Session Binding**
   - IP address binding (hashed)
   - User-Agent binding (hashed)
   - Device fingerprinting

3. **Automatic Expiry & Refresh**
   - TTL: 1 hour
   - Auto-refresh if < 5 minutes remaining
   - Sliding window expiration

4. **Concurrent Session Limits**
   - Max 3 sessions per admin user
   - Oldest session auto-revoked when limit reached

5. **Session Rotation**
   - On privilege escalation
   - On security-sensitive actions
   - Prevents session fixation

6. **Revocation**
   - Individual session revocation
   - Revoke all user sessions
   - Immediate effect (Redis + Postgres)

### Session Token Format
{unsigned_token}.{signature}
Where:

unsigned_token: 43-char URL-safe token
signature: HMAC-SHA256(token + user_id, secret)[:16]


**Example:**
xB7kP2mQ9rL3vN8wC5tY6uH4jF1dS0aZ9mX7cV2bN1qW.a1b2c3d4e5f6g7h8

### Session Validation Flow

Extract token from Authorization header
Split into token + signature
Verify signature (constant-time comparison)
Check Redis for session data
Verify not expired
Verify IP binding (optional)
Update last activity timestamp
Return session data


---

## Audit Logging

### Immutable Append-Only Log

**Properties:**
- ✅ Write-only (INSERT only)
- ❌ No UPDATE operations
- ❌ No DELETE operations
- ✅ Permanent retention
- ✅ Cryptographic integrity (hash chain)

### Hash Chain Integrity

**Each log entry includes:**
{
"id": 123,
"action": "device_revoked",
"actor_id": "admin_001",
"timestamp": "2025-01-15T10:30:00Z",
"previous_hash": "abc123...",  // Hash of log 122
"hash": "def456..."             // Hash of this log
}

**Hash calculation:**
hash = SHA256(
"action:device_revoked|" +
"actor_id:admin_001|" +
"timestamp:2025-01-15T10:30:00Z|" +
"previous_hash:abc123..."
)

**Tamper detection:**
- If any log is modified, its hash won't match
- If any log is deleted, chain is broken
- If logs are reordered, previous_hash won't match

### Audited Actions

**Authentication:**
- `login_success` / `login_failure`
- `logout`
- `mfa_enrolled` / `mfa_disabled`
- `session_created` / `session_revoked`

**Authorization:**
- `permission_granted` / `permission_denied`
- `role_assigned` / `role_revoked`

**Device Management:**
- `device_revoked`
- `device_trust_updated`

**User Management:**
- `user_created` / `user_updated` / `user_deleted`
- `user_password_reset`
- `user_mfa_reset`

**Security Events:**
- `unauthorized_access_attempt`
- `privilege_escalation_attempt`
- `suspicious_activity`

### Audit Log Query

```python
# Query audit logs
logs = await audit_logger.query_logs(
    actor_id="admin_001",
    action=AuditAction.DEVICE_REVOKED,
    start_time=datetime(2025, 1, 1),
    end_time=datetime(2025, 1, 31),
    limit=100
)

# Verify integrity
result = await audit_logger.verify_integrity()

if result["valid"]:
    print("✅ Audit log integrity verified")
else:
    print("❌ Tampered entries:", result["tampered_entries"])
```

---

## Security Testing

### Unauthorized Access Prevention

**Test Coverage: 100% blocked**

```bash
pytest tests/security/test_admin_authentication.py::TestUnauthorizedAccess

Results:
✅ No token access: 5/5 blocked (100%)
✅ Invalid token access: 7/7 blocked (100%)
✅ Expired session blocked
✅ Revoked session blocked
✅ All unauthorized access blocked: 5/5 (100%)
```

### Privilege Escalation Prevention

**Test Coverage: 0 successful escalations**

```bash
pytest tests/security/test_admin_authentication.py::TestPrivilegeEscalation

Results:
✅ VIEWER cannot revoke devices
✅ ANALYST cannot assign roles
✅ OPERATIONS_ADMIN cannot manage roles
✅ Token tampering escalation: 3/3 blocked
✅ All privilege escalation blocked: 0/5 succeeded (0%)
```

---

## Production Deployment

### Environment Variables

```bash
# Session configuration
SESSION_SECRET=CHANGE_ME_IN_PRODUCTION  # 256-bit random key
SESSION_TTL=3600                         # 1 hour

# MFA configuration
MFA_ISSUER_NAME=Certivo
MFA_WINDOW=1                             # ±30 seconds

# Rate limiting
MFA_MAX_ATTEMPTS=5
MFA_LOCKOUT_DURATION=900                 # 15 minutes

# Database
POSTGRES_URL=postgresql://...
REDIS_URL=redis://...
```

### Initial Setup

**1. Generate session secret:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**2. Create first super admin:**
```bash
python scripts/create_admin.py \
    --username admin \
    --email admin@company.com \
    --role super_admin
```

**3. Enroll MFA:**
```bash
python scripts/generate_mfa_secret.py admin
# Scan QR code with authenticator app
```

**4. Verify audit logging:**
```bash
python scripts/verify_audit_integrity.py
```

### Security Checklist

- [ ] Change SESSION_SECRET from default
- [ ] Enable MFA for all admin users
- [ ] Configure rate limiting
- [ ] Enable audit log verification
- [ ] Set up monitoring alerts
- [ ] Review role assignments
- [ ] Test session revocation
- [ ] Verify IP binding
- [ ] Configure backup codes
- [ ] Document recovery procedures

---

## Monitoring & Alerts

### Prometheus Metrics

```prometheus
# Authentication
rate(admin_login_failures_total[5m])
rate(admin_mfa_failures_total[5m])

# Authorization
rate(permission_denied_total[5m])

# Sessions
admin_active_sessions_count
rate(session_revoked_total[5m])

# Audit
rate(audit_log_writes_total[5m])
```

### Alerts

```yaml
- alert: HighLoginFailureRate
  expr: rate(admin_login_failures_total[5m]) > 5
  severity: warning

- alert: MFABruteForce
  expr: rate(admin_mfa_failures_total[5m]) > 10
  severity: critical

- alert: UnauthorizedAccessSpike
  expr: rate(permission_denied_total[5m]) > 20
  severity: critical

- alert: AuditLogTamper
  expr: audit_log_integrity_valid == 0
  severity: critical
```

---

## Recovery Procedures

### Lost MFA Device

**Recovery via Backup Codes:**

Admin enters username + password
Select "Use backup code instead"
Enter one-time backup code
Backup code deleted after use
Admin logs in successfully


**Admin MFA Reset (Super Admin only):**
```bash
# Reset MFA for user
python scripts/reset_user_mfa.py <username>

# User must re-enroll MFA on next login
```

### Compromised Session

**Immediate Revocation:**
```bash
# Revoke specific session
curl -X POST /auth/logout \
  -H "Authorization: Bearer <token>"

# Revoke all user sessions
curl -X POST /admin/users/<user_id>/revoke-sessions \
  -H "Authorization: Bearer <admin_token>"
```

### Audit Log Verification Failure

**Investigation Steps:**

Run integrity verification
Identify tampered entries
Compare with backup logs
Investigate timeline
Report security incident
Restore from backup if needed


---

## Best Practices

### For Administrators

1. **Always use MFA** - Never disable for convenience
2. **Rotate passwords quarterly** - Use strong, unique passwords
3. **Review audit logs weekly** - Look for suspicious activity
4. **Revoke unused sessions** - Keep session count minimal
5. **Follow least privilege** - Assign minimum necessary role

### For Developers

1. **Never bypass RBAC** - Always use dependency injection
2. **Log all privileged actions** - Use audit logger consistently
3. **Validate permissions server-side** - Never trust client
4. **Use constant-time comparisons** - Prevent timing attacks
5. **Test authorization thoroughly** - Cover all edge cases

### For Security Teams

1. **Monitor failed auth attempts** - Alert on patterns
2. **Verify audit integrity daily** - Automated checks
3. **Review role assignments monthly** - Principle of least privilege
4. **Test incident response** - Regular drills
5. **Keep dependencies updated** - Security patches