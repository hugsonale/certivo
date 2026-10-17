# Certivo Admin Dashboard Guide

Complete guide for administrators managing the Certivo verification system.

---

## 📋 Table of Contents

1. [Accessing the Dashboard](#accessing-the-dashboard)
2. [Overview Page](#overview-page)
3. [Sessions Management](#sessions-management)
4. [Challenge Monitoring](#challenge-monitoring)
5. [Trusted Devices](#trusted-devices)
6. [Bot Activity](#bot-activity)
7. [System Logs](#system-logs)
8. [System Health](#system-health)
9. [Common Tasks](#common-tasks)
10. [Troubleshooting](#troubleshooting)

---

## 🔐 Accessing the Dashboard

### Login URL
```
http://your-domain.com/admin/login
```

### Default Credentials
- **Username:** Set in `.env` as `ADMIN_USERNAME`
- **Password:** Set in `.env` as `ADMIN_PASSWORD`

**⚠️ CRITICAL:** Change default password immediately after first login!

### Changing Password

Edit `.env` file:
```bash
ADMIN_PASSWORD=your_new_secure_password_here
```

Restart server:
```bash
uvicorn main:app --reload
```

---

## 📊 Overview Page

**URL:** `/admin/dashboard`

### What You See

#### Verification Statistics (Top Cards)
- **Total Sessions:** All verification attempts
- **Success Rate:** Percentage of passed verifications
- **Avg Liveness Score:** Average authenticity score (0-1)
- **Trusted Devices:** Count of devices with high trust

#### Recent Activity Chart
- **Timeline:** Last 24 hours
- **Metrics:** Successful vs failed verifications
- **Purpose:** Identify unusual patterns

#### Key Metrics
- **Active Challenges:** Currently in-progress verifications
- **Bot Detections (24h):** Suspicious activity caught
- **Rate Limits Hit:** Users hitting attempt limits
- **Trust Revocations (7d):** Devices losing trusted status

### What to Monitor

✅ **Healthy System:**
- Success rate > 75%
- Liveness scores > 0.85
- Bot detections < 5%
- Stable verification count

⚠️ **Warning Signs:**
- Success rate drops below 60%
- Spike in bot detections
- Many rate limit hits
- High trust revocations

---

## 📝 Sessions Management

**URL:** `/admin/sessions`

### Session List
Shows all verification sessions with:
- **Session ID:** Unique identifier
- **Device ID:** Device fingerprint
- **Trust Level:** low/medium/high
- **Trust Score:** 0-100
- **Status:** completed/in-progress
- **Timestamp:** When session occurred

### Filtering
- Search by device ID
- Filter by trust level
- Sort by date/score

### What to Look For

🔍 **Suspicious Patterns:**
- Same device, many failed sessions
- Multiple devices, same IP (check logs)
- Trust score suddenly drops
- Repeated rate limiting

---

## 🎯 Challenge Monitoring

**URL:** `/admin/challenges`

### Challenge Results
Shows individual challenge attempts:
- **Challenge Type:** left/right/blink/nod/mouth/eyebrows
- **Passed/Failed:** Outcome
- **Liveness Score:** Quality metric
- **Direction Match:** For turn challenges
- **Fast Track:** Trusted device flag

### Success Rates by Type
Monitor which challenges have low success:
- **Left/Right:** Should be > 85%
- **Blink:** Should be > 90%
- **Nod:** Should be > 80%
- **Mouth:** Should be > 85%
- **Eyebrows:** Should be > 75%

### Tuning Challenges

If success rate too low:
1. Check `human_verification.py` thresholds
2. Review failed videos (if stored)
3. Adjust difficulty in `challenge_engine.py`

---

## 🛡️ Trusted Devices

**URL:** `/admin/trusted-devices`

### Device List
- **Device ID:** Unique identifier
- **Trust Level:** Current status
- **Verifications:** Total attempts
- **Success Rate:** Pass percentage
- **Last Seen:** Recent activity
- **Trust Status:** Active/Revoked

### Actions

#### Revoke Trust
1. Click **Revoke** next to device
2. Enter reason (required)
3. Confirm

**Effect:**
- Device loses trusted status
- Next verification requires full challenges
- Logged in security logs

#### When to Revoke
- Suspicious activity detected
- Device compromised
- User reports unauthorized access
- Bot patterns identified

---

## 🤖 Bot Activity

**URL:** `/admin/bot-activity`

### Detection Statistics
- **Total Detections:** Count of suspicious activities
- **Detection Rate:** Percentage of attempts flagged
- **Common Patterns:** Most frequent bot behaviors

### Suspicious Devices
List of flagged devices:
- **Device ID**
- **Suspicion Score:** 0-10 (10 = definitely bot)
- **Reason:** Why flagged
- **Timestamp**
- **Status:** Active/Blocked

### Bot Detection Triggers
- Video integrity fails (blank/static)
- Perfect liveness scores (99.99%)
- Identical motion patterns
- Too-fast submissions
- Unusual video metrics

### Response Actions

**For suspicion score 1-5:**
- Monitor closely
- No immediate action

**For suspicion score 6-8:**
- Flag device
- Increase challenge difficulty
- Log for review

**For suspicion score 9-10:**
- Block device
- Review IP in logs
- Consider IP ban

---

## 📋 System Logs

**URL:** `/admin/logs`

### Log Categories

#### Verification Logs
- Challenge requests
- Video uploads
- Pass/fail results
- Performance metrics

#### Security Logs
- Failed login attempts
- Rate limit violations
- Bot detections
- Trust revocations

#### Admin Logs
- Dashboard access
- Trust revocations
- Configuration changes

#### Error Logs
- System exceptions
- Processing failures
- Database errors

### Log Locations
```
logs/certivo.log          # General logs
logs/verification.log     # Verification events
logs/security.log         # Security events
logs/admin.log           # Admin actions
logs/errors.log          # Errors only
```

### Searching Logs
Use grep/findstr to search:
```bash
# Linux/Mac
grep "device_123" logs/verification.log

# Windows
findstr "device_123" logs\verification.log
```

---

## 🏥 System Health

**URL:** `/admin/system-health`

### Metrics Monitored

#### Server Resources
- **CPU Usage:** Should be < 70%
- **Memory Usage:** Should be < 80%
- **Disk Space:** Should have > 10GB free
- **Database Size:** Monitor growth

#### Application Health
- **Active Processes:** Worker count
- **Response Times:** API latency
- **Error Rate:** Should be < 1%
- **Uptime:** Continuous operation

### Health Indicators

🟢 **Healthy:** All metrics in normal range  
🟡 **Warning:** One or more metrics elevated  
🔴 **Critical:** System degraded, action needed  

### When System is Unhealthy

**High CPU:**
- Check for stuck processes
- Review recent traffic spike
- Consider scaling up

**High Memory:**
- Restart application
- Check for memory leaks
- Review database connections

**High Error Rate:**
- Check error logs
- Verify database connection
- Review recent deployments

---

## 🔧 Common Tasks

### Task 1: Investigate Failed Verification

1. Go to **Sessions** page
2. Find session by device ID or time
3. Click session to see details
4. Review challenge results
5. Check liveness scores
6. Look for error codes in logs

### Task 2: Handle Bot Attack

1. Go to **Bot Activity** page
2. Identify suspicious devices
3. Check detection patterns
4. Block high-suspicion devices
5. Monitor for continued activity
6. Consider IP-level blocking

### Task 3: Review System Performance

1. Go to **System Health** page
2. Check resource usage
3. Review response times
4. Check error rates
5. Visit **Logs** if issues found

### Task 4: Adjust Challenge Difficulty

1. Go to **Challenges** page
2. Check success rates by type
3. Note problematic challenges
4. Update thresholds in code
5. Test changes
6. Monitor new success rates

---

## 🐛 Troubleshooting

### Problem: Low Success Rate (<60%)

**Possible Causes:**
- Thresholds too strict
- Poor lighting instructions
- Browser compatibility issues
- Challenge instructions unclear

**Solutions:**
1. Review failed challenges
2. Check error codes
3. Adjust detection thresholds
4. Improve user instructions
5. Test in multiple browsers

---

### Problem: High Bot Detection Rate (>10%)

**Possible Causes:**
- Legitimate users flagged incorrectly
- Actual bot attack
- Video integrity checks too strict

**Solutions:**
1. Review flagged videos (if stored)
2. Check bot detection patterns
3. Adjust integrity thresholds
4. Verify detection logic
5. Consider IP patterns

---

### Problem: System Slow/Unresponsive

**Possible Causes:**
- Database lock-up
- Memory leak
- High concurrent load
- Disk space full

**Solutions:**
1. Check System Health page
2. Restart application
3. Check database connections
4. Review error logs
5. Scale resources if needed

---

### Problem: Users Can't Complete Verification

**Possible Causes:**
- Rate limiting too aggressive
- Challenge expiration too short
- Browser camera issues
- Network problems

**Solutions:**
1. Check rate limit settings
2. Verify challenge timeout (5 min)
3. Test in multiple browsers
4. Review network logs
5. Provide troubleshooting guide

---

## 📞 Emergency Contacts

### Critical Issues
- **Database Down:** Check database.py connection
- **Server Crash:** Check logs/errors.log
- **Security Breach:** Revoke all trust, investigate

### Escalation Path
1. Check System Health
2. Review Error Logs
3. Check Database Connection
4. Restart Application
5. Contact System Administrator

---

## 📚 Additional Resources

- [Error Codes Reference](ERROR_CODES.md)
- [Deployment Guide](DEPLOYMENT.md)
- [Architecture Overview](ARCHITECTURE.md)
- [API Documentation](http://your-domain.com/docs)

---

## 🔒 Security Best Practices

✅ **Do:**
- Change default admin password immediately
- Review logs daily
- Monitor bot activity
- Keep trust revocation reasons documented
- Backup database regularly

❌ **Don't:**
- Share admin credentials
- Ignore bot detection alerts
- Disable security features
- Skip regular monitoring
- Deploy without HTTPS

---

**Last Updated:** 2026-03-12  
**Version:** 1.0.0