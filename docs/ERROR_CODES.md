# Certivo Error Codes Reference

Complete reference for all error codes returned by the Certivo API.

---

## Verification Errors

### `RATE_LIMIT_EXCEEDED`
**HTTP Status:** 429  
**Cause:** Too many verification attempts in short time  
**User Action:** Wait 5 minutes before trying again  
**Admin Action:** Check for bot activity if repeated  

### `DEVICE_BLOCKED`
**HTTP Status:** 403  
**Cause:** Device flagged for suspicious activity  
**User Action:** Contact support  
**Admin Action:** Review device in admin dashboard, revoke trust if needed  

### `INVALID_FORMAT`
**HTTP Status:** 400  
**Cause:** Video file format not supported  
**User Action:** Ensure camera is working, try different browser  
**Admin Action:** None  

### `VIDEO_INTEGRITY_FAILED`
**HTTP Status:** 400  
**Cause:** Video appears blank, static, or manipulated  
**User Action:** Ensure good lighting, stable camera  
**Admin Action:** Check bot detection logs  

### `CHALLENGE_NOT_FOUND`
**HTTP Status:** 404  
**Cause:** Challenge ID doesn't exist or expired  
**User Action:** Start new verification  
**Admin Action:** None  

### `INVALID_TOKEN`
**HTTP Status:** 403  
**Cause:** Verification token mismatch  
**User Action:** Start new verification  
**Admin Action:** Check for replay attacks  

### `DEVICE_MISMATCH`
**HTTP Status:** 403  
**Cause:** Challenge belongs to different device  
**User Action:** Start new verification  
**Admin Action:** Check for session hijacking  

### `CHALLENGE_EXPIRED`
**HTTP Status:** 410  
**Cause:** Challenge expired (5 minute limit)  
**User Action:** Start new verification  
**Admin Action:** None  

### `CHALLENGE_ALREADY_USED`
**HTTP Status:** 409  
**Cause:** Challenge already submitted  
**User Action:** Start new verification  
**Admin Action:** Check for replay attacks  

### `PROCESSING_ERROR`
**HTTP Status:** 500  
**Cause:** Server error during video processing  
**User Action:** Try again  
**Admin Action:** Check logs for stack trace  

---

## Challenge Detection Errors

### `VIDEO_NOT_FOUND`
**Cause:** Video file not accessible  
**User Action:** Ensure stable internet connection  

### `VIDEO_TOO_SHORT`
**Cause:** Recording less than 2 seconds  
**User Action:** Hold position for full countdown  

### `NO_FACE_DETECTED`
**Cause:** Face not visible in sufficient frames  
**User Action:** Center face, improve lighting  

### `ACTION_NOT_DETECTED`
**Cause:** Challenge action not performed clearly  
**User Action:** Perform action more deliberately  

### `DIRECTION_MISMATCH`
**Cause:** Moved in wrong direction  
**User Action:** Follow on-screen instruction carefully  

---

## Rate Limits

| Endpoint | Limit | Window |
|----------|-------|--------|
| `/v1/challenge` | 20 requests | 1 minute |
| `/v1/verify` | 5 requests | 5 minutes |
| `/v1/finalize` | 10 requests | 1 minute |

---

## Trust Revocation Triggers

Automatic trust revocation occurs when:
- 3 consecutive failed verifications
- Suspicious video metrics detected
- Manual revocation by admin

---

## Response Format

All errors follow this structure:
```json
{
  "challenge_passed": false,
  "error": "User-friendly message",
  "error_code": "ERROR_CODE_HERE",
  "error_details": "Technical details for debugging"
}
```

---

## Getting Help

- Check logs: `logs/errors.log`
- Admin dashboard: `http://your-domain.com/admin`
- System health: `http://your-domain.com/admin/system-health`