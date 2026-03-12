# Certivo System Architecture

Technical overview of the Certivo human verification system architecture, design decisions, and data flow.

---

## 📋 Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Diagram](#architecture-diagram)
3. [Component Breakdown](#component-breakdown)
4. [Data Flow](#data-flow)
5. [Database Schema](#database-schema)
6. [Security Architecture](#security-architecture)
7. [Performance Optimization](#performance-optimization)
8. [Design Decisions](#design-decisions)
9. [Scalability Considerations](#scalability-considerations)
10. [Technology Stack](#technology-stack)

---

## 🎯 System Overview

Certivo is an **adaptive human verification system** that uses real-time video challenges and AI-powered liveness detection to distinguish humans from bots.

### Core Capabilities
- **Adaptive Challenges:** Difficulty adjusts based on device trust level
- **Liveness Detection:** Real-time face detection and movement analysis
- **Bot Detection:** Multi-layer security to identify automated attacks
- **Trust Scoring:** Device reputation system with automatic trust management
- **Rate Limiting:** Protection against brute force attacks
- **Admin Dashboard:** Real-time monitoring and management interface

### Design Philosophy
1. **Security First:** Multiple validation layers at every step
2. **User Experience:** Trusted devices get faster, easier challenges
3. **Performance:** Sub-3-second verification processing
4. **Observability:** Comprehensive logging and metrics
5. **Maintainability:** Modular design with clear separation of concerns

---

## 🏗️ Architecture Diagram
```
┌─────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Browser    │  │   Mobile     │  │  Admin UI    │          │
│  │  (Camera)    │  │  (Camera)    │  │  Dashboard   │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                  │                  │                   │
└─────────┼──────────────────┼──────────────────┼──────────────────┘
          │                  │                  │
          ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────────────┐
│                      API GATEWAY (NGINX)                         │
│  • HTTPS Termination  • Rate Limiting  • Load Balancing          │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                    FASTAPI APPLICATION                           │
│  ┌────────────────────────────────────────────────────────┐    │
│  │  MAIN.PY (API Routes)                                   │    │
│  │  ├─ /v1/challenge      (Generate challenges)            │    │
│  │  ├─ /v1/verify         (Process video)                  │    │
│  │  ├─ /v1/finalize       (Calculate trust)                │    │
│  │  └─ /admin/*           (Admin endpoints)                │    │
│  └────────────┬───────────────────────────────────────────┘    │
│               │                                                  │
│  ┌────────────┼────────────────────────────────────────────┐   │
│  │  BUSINESS LOGIC LAYER                                    │   │
│  │  ┌──────────────────┐  ┌──────────────────┐            │   │
│  │  │ challenge_engine │  │ human_verification│            │   │
│  │  │  - Adaptive gen  │  │  - Face detection │            │   │
│  │  │  - Difficulty    │  │  - Movement track │            │   │
│  │  └──────────────────┘  └──────────────────┘            │   │
│  │                                                           │   │
│  │  ┌──────────────────┐  ┌──────────────────┐            │   │
│  │  │  bot_detector    │  │  rate_limiter    │            │   │
│  │  │  - Pattern match │  │  - IP + Device   │            │   │
│  │  │  - Video metrics │  │  - Sliding window│            │   │
│  │  └──────────────────┘  └──────────────────┘            │   │
│  └───────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  DATA ACCESS LAYER                                      │   │
│  │  ┌──────────────────────────────────────────────┐      │   │
│  │  │  DATABASE.PY (SQLAlchemy ORM)                │      │   │
│  │  │  - Session management                         │      │   │
│  │  │  - Challenge CRUD                             │      │   │
│  │  │  - Trust operations                           │      │   │
│  │  └──────────────────────────────────────────────┘      │   │
│  └────────────┬───────────────────────────────────────────┘   │
└───────────────┼──────────────────────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     PERSISTENCE LAYER                            │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │  SQLite/Postgres │  │   File Storage   │                    │
│  │  - Sessions      │  │  - Temp videos   │                    │
│  │  - Challenges    │  │  - Logs          │                    │
│  │  - Trusted devs  │  │                  │                    │
│  └──────────────────┘  └──────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                   OBSERVABILITY LAYER                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Logger     │  │  Prometheus  │  │    Sentry    │          │
│  │  (JSON logs) │  │  (Metrics)   │  │ (Error track)│          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🧩 Component Breakdown

### 1. **main.py** - API Gateway
**Purpose:** FastAPI application entry point, route definitions, middleware

**Key Responsibilities:**
- Route all incoming HTTP requests
- Apply middleware (CORS, rate limiting)
- Dependency injection (database sessions)
- Error handling and response formatting
- Prometheus metrics collection
- Sentry integration

**Key Endpoints:**
```python
GET  /v1/challenge              # Generate verification challenges
POST /v1/verify                 # Submit video for verification
POST /v1/finalize              # Finalize session and calculate trust
GET  /v1/device/{id}/stats     # Device statistics
GET  /admin/*                  # Admin dashboard routes
GET  /metrics                  # Prometheus metrics
```

---

### 2. **challenge_engine.py** - Challenge Generator
**Purpose:** Adaptive challenge generation based on device trust

**Algorithm:**
```python
def generate_adaptive_challenges(trusted, prev_results):
    if trusted:
        return 1 easy challenge
    else if prev_results has failures:
        return 2 hard challenges
    else:
        return 2 medium challenges
```

**Challenge Types:**
- **left/right:** Head turn detection (nose-tip tracking)
- **blink:** Eye aspect ratio (EAR) analysis
- **nod:** Vertical head movement tracking
- **mouth:** Mouth aspect ratio (MAR) detection
- **eyebrows:** Eyebrow-to-eye distance measurement

**Difficulty Levels:**
```python
easy:   Lower thresholds, more tolerant
medium: Standard thresholds
hard:   Stricter thresholds, more frames required
```

---

### 3. **human_verification.py** - Liveness Detection Engine
**Purpose:** Video analysis and movement detection using OpenCV + MediaPipe

**Architecture:**
```
Video Input
    ↓
Frame Extraction (every 3rd frame for speed)
    ↓
MediaPipe Face Mesh (468 landmarks)
    ↓
Movement Detection (challenge-specific)
    ↓
Liveness Score Calculation
    ↓
Pass/Fail Decision
```

**Detection Methods:**

#### Head Turn (left/right)
```python
1. Track nose tip X position across frames
2. Calculate start_x (first quartile) vs end_x (last quartile)
3. delta = end_x - start_x
4. if |delta| > threshold and direction matches: PASS
```

#### Blink Detection
```python
1. Calculate Eye Aspect Ratio (EAR) per frame
2. EAR = (vertical_distance) / (horizontal_distance)
3. Track state: open → closed → open = 1 blink
4. if blinks >= 2: PASS
```

#### Nod Detection
```python
1. Track nose tip Y position
2. Smooth with moving average
3. Count direction changes (up → down → up)
4. if cycles >= 1 and range > threshold: PASS
```

#### Mouth Open
```python
1. Calculate Mouth Aspect Ratio (MAR)
2. MAR = (vertical_distance) / (horizontal_distance)
3. if MAR > threshold for >= 5 frames: PASS
```

#### Eyebrow Raise
```python
1. Calculate eyebrow-to-eye distance
2. Establish baseline (first 20% of frames)
3. if (current - baseline) > threshold for >= 5 frames: PASS
```

**Performance Optimizations:**
- Model caching (reuse MediaPipe instance)
- Frame sampling (process every 3rd frame → 2x speed)
- Early exit (stop if enough data collected)
- Target: < 3000ms processing time

---

### 4. **database.py** - Data Persistence Layer
**Purpose:** SQLAlchemy ORM models and database operations

**Schema Overview:**
```
SessionRecord
├─ session_id (PK)
├─ device_id
├─ trust_score (0-100)
├─ trust_level (low/medium/high)
└─ timestamps

ChallengeResult
├─ id (PK)
├─ session_id (FK)
├─ challenge_id
├─ challenge_passed (bool)
├─ liveness_score (0-1)
├─ action_detected
└─ timestamps

TrustedDevice
├─ id (PK)
├─ device_id
├─ trust_level
├─ verification_count
├─ trust_revoked (bool)
├─ revoked_at
└─ revocation_reason

ActiveChallenge
├─ id (PK)
├─ challenge_id (unique)
├─ device_id
├─ token_id
├─ expected_movement
├─ expires_at (5 min TTL)
└─ used (bool)

SuspiciousDevice
├─ id (PK)
├─ device_id
├─ suspicion_score (0-10)
├─ reason
└─ timestamp

BotReport
├─ id (PK)
├─ device_id
├─ detection_type
├─ confidence_score
└─ timestamp
```

**Key Operations:**
```python
# Challenge lifecycle
store_challenge()      # Create new challenge
get_challenge()        # Retrieve by ID
delete_challenge()     # Remove after use

# Trust management
is_device_trusted()    # Check trust status
update_device_trust()  # Update trust level
revoke_device_trust()  # Revoke with reason

# Results tracking
store_challenge_result()  # Save attempt
get_session_results()     # Get device history
```

---

### 5. **rate_limiter.py** - Rate Limiting
**Purpose:** Prevent abuse with sliding window rate limiting

**Algorithm:**
```python
For each (IP + device_id + endpoint):
    Track: [timestamp1, timestamp2, timestamp3, ...]
    Remove timestamps older than window
    If count > limit: REJECT
    Else: ALLOW and add new timestamp
```

**Limits:**
```python
/v1/challenge: 20 requests / 1 minute
/v1/verify:    5 requests / 5 minutes
/v1/finalize:  10 requests / 1 minute
```

**Failed Attempt Lockout:**
```
5 failed verifications → 5 minute cooldown
```

---

### 6. **bot_detector.py** - Bot Detection
**Purpose:** Identify automated attacks using behavioral analysis

**Detection Signals:**

1. **Video Integrity Checks**
   - Blank frames (all black/white)
   - Static images (no motion)
   - Duplicate frames (>95% same)

2. **Video Metrics Analysis**
   - Perfect liveness scores (99.99% = suspicious)
   - Low motion variance
   - Unnaturally high face detection rate
   - Too-fast submission times

3. **Pattern Matching**
   - Identical movement patterns
   - Same video submitted multiple times
   - Sequential device IDs

**Suspicion Scoring (0-10):**
```
0-3:  Low risk (monitor)
4-6:  Medium risk (flag)
7-8:  High risk (strict mode)
9-10: Certain bot (block)
```

---

### 7. **logger.py** - Logging System
**Purpose:** Structured JSON logging to multiple files

**Log Files:**
```
logs/certivo.log       # General application logs
logs/verification.log  # Challenge attempts
logs/security.log      # Security events
logs/admin.log         # Admin actions
logs/errors.log        # Errors only
```

**Log Format (JSON):**
```json
{
  "timestamp": "2026-03-12T10:30:45.123Z",
  "level": "INFO",
  "event": "challenge_passed",
  "session_id": "device_abc123",
  "challenge_id": "chal_xyz789",
  "details": {
    "movement": "left",
    "liveness_score": 0.96
  }
}
```

**Key Events Logged:**
- challenge_requested
- challenge_passed / challenge_failed
- trust_updated / trust_revoked
- bot_detected
- rate_limit_hit
- admin_action

---

### 8. **admin/** - Admin Dashboard
**Purpose:** Web-based monitoring and management interface

**Components:**
```
admin/
├─ routes.py      # FastAPI routes
├─ auth.py        # Session authentication
├─ config.py      # Configuration
├─ services.py    # Business logic
├─ utils.py       # Helper functions
└─ templates/     # Jinja2 HTML templates
```

**Pages:**
1. **Dashboard** - Overview metrics and charts
2. **Sessions** - All verification sessions
3. **Challenges** - Challenge results
4. **Trusted Devices** - Device management
5. **Bot Activity** - Suspicious devices
6. **Logs** - System logs viewer
7. **System Health** - Server metrics

**Authentication:**
- Username/password login
- Session cookies (secure, httponly)
- CSRF protection
- Auto-logout after 24 hours

---

## 🔄 Data Flow

### Complete Verification Flow
```
1. USER REQUESTS CHALLENGE
   Browser → GET /v1/challenge?device_id=X
       ↓
   Rate Limiter checks (20/min limit)
       ↓
   Challenge Engine generates 1-2 challenges
       ↓
   Store in ActiveChallenge table
       ↓
   Return: {challenges: [...], tokens: [...]}

2. USER RECORDS VIDEO
   Browser captures video (MediaRecorder API)
       ↓
   Timer: 3-5 seconds
       ↓
   Video encoded as WebM/MP4

3. USER SUBMITS VIDEO
   Browser → POST /v1/verify
       ↓
   Rate Limiter checks (5/5min limit)
       ↓
   Device flagging check (blocked?)
       ↓
   Video format validation
       ↓
   Save to temp file
       ↓
   Video integrity checks (blank/static/motion)
       ↓
   Load challenge from database
       ↓
   Validate: token, device_id, expiration, not used
       ↓
   Run human_verification.py
       ├─ Extract frames
       ├─ Detect face with MediaPipe
       ├─ Track movement (challenge-specific)
       ├─ Calculate liveness score
       └─ Return pass/fail
       ↓
   Bot detection analysis
       ↓
   Store result in ChallengeResult
       ↓
   Delete challenge (mark as used)
       ↓
   Check for trust revocation (3 consecutive fails)
       ↓
   Return: {challenge_passed, liveness_score, ...}

4. USER FINALIZES SESSION
   Browser → POST /v1/finalize
       ↓
   Get all results for device
       ↓
   Calculate trust score:
       success_rate = passed / total
       avg_liveness = mean(liveness_scores)
       trust_score = (success_rate * 70) + (avg_liveness * 30)
       ↓
   Determine trust level:
       trust_score >= 85 → high
       trust_score >= 60 → medium
       trust_score <  60 → low
       ↓
   Update TrustedDevice table
       ↓
   Store SessionRecord
       ↓
   Return: {trust_score, trust_level, verified: true/false}
```

---

## 🗄️ Database Schema

### Entity Relationship Diagram
```
SessionRecord
├─ PK: session_id
└─ device_id
     │
     ├─→ ChallengeResult
     │   ├─ FK: session_id
     │   └─ challenge_id
     │
     ├─→ TrustedDevice
     │   └─ device_id
     │
     └─→ SuspiciousDevice
         └─ device_id

ActiveChallenge
└─ challenge_id (unique, expires after 5 min)
```

### Indexes
```sql
CREATE INDEX idx_session_device ON session_record(device_id);
CREATE INDEX idx_challenge_device ON challenge_result(device_id);
CREATE INDEX idx_trusted_device ON trusted_device(device_id);
CREATE INDEX idx_challenge_id ON active_challenge(challenge_id);
CREATE INDEX idx_challenge_expires ON active_challenge(expires_at);
```

---

## 🔒 Security Architecture

### Defense in Depth (7 Layers)

**Layer 1: Network (Nginx)**
- HTTPS only
- Rate limiting (global)
- DDoS protection
- Request size limits (10MB max)

**Layer 2: API Gateway (FastAPI)**
- CORS restrictions
- Input validation
- Request sanitization

**Layer 3: Rate Limiting (rate_limiter.py)**
- Per-endpoint limits
- IP + device fingerprint tracking
- Sliding window algorithm
- Automatic lockout (5 failures)

**Layer 4: Device Flagging**
- Suspicious device tracking
- Suspicion score (0-10)
- Automatic blocking (score >= 9)

**Layer 5: Video Integrity**
- Format validation (WebM/MP4 only)
- Size validation (10MB max)
- Blank frame detection
- Static image detection
- Motion variance analysis

**Layer 6: Bot Detection**
- Video metrics analysis
- Pattern matching
- Behavioral analysis
- Automatic flagging

**Layer 7: Trust Revocation**
- 3 consecutive failures → revoke trust
- Manual admin revocation
- Reason tracking
- Re-verification required

---

## ⚡ Performance Optimization

### Implemented Optimizations

1. **Model Caching**
   - MediaPipe FaceMesh: Singleton pattern
   - OpenCV Cascades: Cached instances
   - **Impact:** 500ms saved per verification

2. **Frame Sampling**
   - Process every 3rd frame
   - **Impact:** 2x speed improvement

3. **Database Connection Pooling**
   - Pool size: 10
   - Max overflow: 20
   - **Impact:** Handles 50+ concurrent users

4. **Early Exit Logic**
   - Stop processing when enough data collected
   - **Impact:** 20-30% faster on average

5. **Async Processing**
   - `async def process_verification_async()`
   - Non-blocking file I/O
   - **Impact:** Better concurrency

### Performance Targets
```
Verification Processing: < 3000ms (target: 1500ms)
API Response Time:       < 100ms
Database Query:          < 50ms
Challenge Generation:    < 20ms
```

### Current Performance (Phase 5 Load Test)
```
RPS: 17.23 requests/second
Median Response: 4ms (device stats)
95th Percentile: 10ms
99th Percentile: 23ms
Failure Rate: 0%
Capacity: 1,000+ verifications/hour
```

---

## 🎨 Design Decisions

### 1. **Why SQLite for Default Database?**
**Decision:** Use SQLite for initial deployment, support PostgreSQL

**Reasoning:**
- ✅ Zero configuration
- ✅ File-based (easy backups)
- ✅ Sufficient for 10,000+ verifications/day
- ✅ Easy migration to Postgres later

**When to switch:** > 50,000 verifications/day or distributed deployment

---

### 2. **Why MediaPipe over dlib?**
**Decision:** Use MediaPipe as primary, OpenCV Haar Cascades as fallback

**Reasoning:**
- ✅ Faster (GPU-accelerated)
- ✅ More accurate (468 landmarks vs 68)
- ✅ Better mobile support
- ✅ Active maintenance

**Fallback to OpenCV:** When MediaPipe unavailable (dependency issues)

---

### 3. **Why Adaptive Challenges?**
**Decision:** Trusted devices get 1 easy challenge, new devices get 2 medium

**Reasoning:**
- ✅ Better UX for returning users
- ✅ Maintains security for new devices
- ✅ Reduces friction (47% faster for trusted)
- ✅ Incentivizes legitimate use

**Trade-off:** Slightly less secure for trusted devices (acceptable)

---

### 4. **Why 5-Minute Challenge Expiration?**
**Decision:** Challenges expire after 5 minutes

**Reasoning:**
- ✅ Prevents replay attacks
- ✅ Enough time for users (99% complete in < 2 min)
- ✅ Keeps database clean (auto-cleanup)

**Alternative considered:** 10 minutes (too long, security risk)

---

### 5. **Why Trust Revocation After 3 Failures?**
**Decision:** Revoke trust after 3 consecutive failures

**Reasoning:**
- ✅ Balances security and UX
- ✅ Catches compromised devices quickly
- ✅ Allows for user error (1-2 failures OK)

**Data:** 95% of legitimate users pass within 2 attempts

---

### 6. **Why JSON Logging?**
**Decision:** Structured JSON logs instead of plain text

**Reasoning:**
- ✅ Machine-parseable
- ✅ Easy log aggregation (ELK, Datadog)
- ✅ Searchable with jq/grep
- ✅ Structured queries

**Trade-off:** Slightly less human-readable (acceptable)

---

## 📈 Scalability Considerations

### Current Limits (Single Server)
```
Concurrent Users: 50+
Verifications/Hour: 1,000+
Verifications/Day: 20,000+
Database Size: ~100MB/day
```

### Scaling Strategies

#### Horizontal Scaling (>50,000 verifications/day)
```
┌─────────┐
│  Nginx  │ (Load Balancer)
│  (LB)   │
└────┬────┘
     │
     ├─→ FastAPI Instance 1
     ├─→ FastAPI Instance 2
     └─→ FastAPI Instance 3
          ↓
     PostgreSQL (Shared)
```

**Changes needed:**
- Switch to PostgreSQL
- Add Redis for rate limiting
- Shared session storage
- Distributed file storage (S3)

#### Vertical Scaling (Easy Win)
- Increase to 8+ CPU cores
- 16GB+ RAM
- SSD storage
- **Impact:** 2-3x capacity

#### Database Scaling
- Add read replicas
- Implement caching (Redis)
- Partition by device_id
- Archive old sessions

---

## 🛠️ Technology Stack

### Backend
- **Framework:** FastAPI 0.104.1
- **Server:** Uvicorn (ASGI)
- **ORM:** SQLAlchemy 2.0
- **Database:** SQLite (default) / PostgreSQL (production)

### Computer Vision
- **Face Detection:** MediaPipe 0.10.8
- **Image Processing:** OpenCV 4.8.1
- **Numerical:** NumPy 1.26.2

### Security
- **Password Hashing:** bcrypt 4.1
- **Environment:** python-dotenv 1.0
- **Rate Limiting:** Custom sliding window

### Monitoring
- **Metrics:** Prometheus Client 0.19
- **Logging:** Python logging (JSON)
- **Error Tracking:** Sentry (optional)
- **Health Checks:** psutil 5.9.6

### Frontend
- **Templates:** Jinja2 3.1.2
- **Admin UI:** Vanilla JS + CSS
- **Charts:** Chart.js (CDN)
- **Camera:** MediaRecorder API

### Testing
- **Framework:** pytest 7.4.3
- **Async:** pytest-asyncio 0.21
- **Coverage:** pytest-cov 4.1
- **HTTP Client:** httpx 0.25
- **Load Testing:** Locust 2.20

### Deployment
- **Process Manager:** systemd / supervisor
- **Reverse Proxy:** Nginx
- **TLS:** Let's Encrypt / Certbot
- **OS:** Ubuntu 22.04 LTS (recommended)

---

## 📊 Metrics & Observability

### Prometheus Metrics Exported
```python
# Counters
certivo_verification_success_total{challenge_type}
certivo_verification_failure_total{challenge_type, failure_reason}
certivo_bot_detections_total{detection_type}
certivo_rate_limits_total{endpoint}

# Histogram
certivo_verification_duration_seconds{challenge_type}

# Gauge
certivo_active_verifications
```

### Log Events Tracked
```
- challenge_requested
- challenge_passed
- challenge_failed
- video_integrity_failed
- bot_detected
- trust_updated
- trust_revoked
- rate_limit_hit
- admin_action
- detection_exception
- endpoint_error
```

---

## 🔮 Future Enhancements

### Planned Features
- [ ] Multi-language support
- [ ] Mobile SDK (iOS/Android)
- [ ] WebAuthn integration
- [ ] Risk-based authentication
- [ ] ML-based bot detection
- [ ] A/B testing framework
- [ ] Real-time dashboard (WebSocket)

### Performance Improvements
- [ ] Video streaming (no upload wait)
- [ ] Edge caching (CDN)
- [ ] GPU acceleration
- [ ] WASM face detection (client-side)

### Security Enhancements
- [ ] Behavioral biometrics
- [ ] Device fingerprinting v2
- [ ] IP reputation scoring
- [ ] CAPTCHA fallback

---

**Architecture Version:** 1.0.0  
**Last Updated:** 2026-03-12  
**Author:** Certivo Team