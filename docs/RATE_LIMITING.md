# Rate Limiting & Anti-Abuse System

## Overview

Certivo implements a **multi-dimensional distributed rate limiting system** with progressive penalties to prevent abuse while maintaining legitimate user experience.

## Dimensions

### 1. IP Address
- **Limit:** 100 requests/minute
- **Soft Throttle:** 70 requests
- **Hard Block:** 100 requests
- **Ban Duration:** 1 hour

### 2. Subnet (IPv4 /24, IPv6 /64)
- **Limit:** 500 requests/minute
- **Soft Throttle:** 350 requests
- **Hard Block:** 500 requests
- **Ban Duration:** 2 hours

### 3. ASN (Autonomous System)
- **Limit:** 1,000 requests/minute
- **Soft Throttle:** 700 requests
- **Hard Block:** 1,000 requests
- **Ban Duration:** 4 hours

### 4. Device Fingerprint
- **Limit:** 10 requests/minute
- **Soft Throttle:** 7 requests
- **Hard Block:** 10 requests
- **Ban Duration:** 30 minutes

### 5. Session
- **Limit:** 5 challenges/5 minutes
- **Soft Throttle:** 4 challenges
- **Hard Block:** 5 challenges
- **Ban Duration:** 10 minutes

### 6. Challenge ID
- **Limit:** 3 verifications/5 minutes
- **Soft Throttle:** 2 verifications
- **Hard Block:** 3 verifications
- **Ban Duration:** 15 minutes

## Progressive Penalties

### Level 1: None
- **Condition:** Below soft throttle threshold
- **Action:** Normal processing
- **Headers:** `X-RateLimit-*` informational

### Level 2: Soft Throttle
- **Condition:** Between soft throttle and hard block
- **Action:** Add 0.5-2 second delay
- **Headers:** `X-RateLimit-Throttled: true`
- **Purpose:** Gentle slowdown without blocking

### Level 3: Hard Block
- **Condition:** Exceeds hard block limit
- **Action:** Return 429 error
- **Headers:** `Retry-After: {seconds}`
- **Purpose:** Stop excessive requests

### Level 4: Temporary Ban
- **Condition:** Repeated hard blocks
- **Action:** Ban for configured duration
- **Purpose:** Force cooldown period

## Distributed Enforcement

### Redis-Based Coordination

┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Replica 1  │────▶│    Redis    │◀────│  Replica 2  │
└─────────────┘     │  (Central)  │     └─────────────┘
└─────────────┘
▲
│
┌─────────────┐
│  Replica 3  │
└─────────────┘

**Atomic Operations:**
- `INCR` for counter increment
- `EXPIRE NX` for TTL initialization
- Pipeline for consistency

**Consistency Guarantee:**
- Limits enforced correctly across 3+ replicas
- No race conditions under concurrent load
- No over-allowance due to distributed state

## Bypass Detection

### IP Rotation Detection

```python
# Track device-IP mapping
device_ip_map[device_id] = current_ip

# Detect rotation
if previous_ip != current_ip:
    bypass_attempts["ip_rotation"] += 1
```

**Cost Increase Metric:**
- Each bypass attempt tracked
- Monitored via `/metrics/bypass-attempts`
- Alerts trigger on threshold

### Attack Cost Analysis

| Attack Type | Without Rate Limiting | With Rate Limiting | Cost Multiplier |
|-------------|----------------------|-------------------|-----------------|
| Simple spam | 1000 req/sec | 100 req/min | **600x** |
| IP rotation | Unlimited | Tracked + penalized | **∞** (banned) |
| Distributed attack | Unlimited | ASN-level limits | **Network-wide ban** |

## WAF Integration

### Edge Layer (Cloudflare/AWS WAF)
- Bot detection
- IP reputation filtering
- Geographic blocking
- DDoS mitigation

### Application Layer (API Gateway)
- Multi-dimensional limits
- Progressive penalties
- Bypass detection

### Combined Protection

