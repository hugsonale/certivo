diff --git a/docs/DEEP_DUE_DILIGENCE_2026-04-03.md b/docs/DEEP_DUE_DILIGENCE_2026-04-03.md
new file mode 100644
index 0000000000000000000000000000000000000000..ad56569469201a4d061e2070bb42d037da673dc9
--- /dev/null
+++ b/docs/DEEP_DUE_DILIGENCE_2026-04-03.md
@@ -0,0 +1,165 @@
+# Certivo Deep Technical Due Diligence (2026-04-03)
+
+## Executive Summary
+Certivo has a strong prototype-level narrative (adaptive challenges + trust scoring + admin dashboard), but the current implementation has severe security and architecture gaps that make it **not investment-ready** for high-stakes anti-bot use today.
+
+Core issues include:
+- replay resistance is weak;
+- anti-automation controls are bypassable;
+- rate-limiting is partially disabled and not production-safe;
+- trust model is easy to game;
+- storage/privacy controls for biometric data are under-defined.
+
+## 1) What the system is (in plain language)
+Certivo is a FastAPI service that asks users to record short webcam videos while performing simple face actions (turn left/right, blink, nod, open mouth, raise eyebrows). The backend uses OpenCV/MediaPipe heuristics to classify whether the action happened, then computes a trust score and labels devices as low/medium/high trust for future sessions.
+
+## 2) Architecture observed
+### Backend
+- Monolithic `main.py` holds API routes, rate limiting, bot checks, metrics, and workflow orchestration.
+- `challenge_engine.py` generates challenge prompts and adjusts difficulty from recent outcomes.
+- `human_verification.py` performs liveness/action detection with thresholds.
+- `database.py` contains SQLAlchemy models and all CRUD logic.
+- Admin subsystem (`admin/`) provides dashboards and device management.
+
+### Frontend
+- Single-page HTML app (`index.html`) with multiple screen states and inlined JS/CSS.
+- Uses browser MediaRecorder, submits raw video to backend endpoints.
+- Uses hardcoded localhost API URLs currently.
+
+### Data flow
+1. Client requests `/v1/challenge?device_id=...`.
+2. Backend returns one or two challenge(s) with `challenge_id` + `token_id`.
+3. Client records ~3s clip and posts to `/v1/verify` with video + IDs.
+4. Backend validates challenge, processes video, stores per-challenge result.
+5. Client calls `/v1/finalize` with session results; backend computes trust.
+
+## 3) Critical security findings
+### A. Rate limiting is effectively broken in critical path
+- `/v1/challenge` rate-limit enforcement appears commented out in a triple-quoted block.
+- `/v1/verify` uses `client_ip = "rate_limited"` rather than real request IP, collapsing all traffic into one pseudo-IP bucket.
+Impact: easy abuse, false global throttling, poor attacker attribution.
+
+### B. Challenge predictability and low entropy
+- Challenge pool is tiny and deterministic category-wise (few action types).
+- Attackers can pre-train automation agents for the small finite challenge set.
+Impact: low-cost bypass once motion synthesis loop is tuned.
+
+### C. Replay/pre-recorded attack resistance is weak
+- Integrity checks rely on brightness variance, frame diff, duplicate ratio.
+- No robust nonce-binding to per-frame watermark/challenge phrase, no cryptographic signed capture metadata.
+Impact: pre-recorded or composited videos can pass with modest effort.
+
+### D. Trust model can be gamed
+- `/v1/finalize` accepts client-provided `results` body and can compute trust from that when DB results are missing.
+- Device identity appears client-controlled (`device_id` generated in frontend using `Math.random`).
+Impact: spoofable identity and potential score manipulation.
+
+### E. Public admin-ish intelligence endpoint
+- `/v1/admin/bot-stats` is exposed without admin auth dependency.
+Impact: attacker recon on detection quality and suspicious-device counts.
+
+## 4) Video verification quality critique
+Current approach is heuristic thresholding, not robust liveness proof:
+- No challenge audio phrase / randomized lexical prompt.
+- No 3D anti-spoof (depth/parallax/IR) or screen-reflection analysis.
+- No active anti-deepfake checks (dedicated deepfake detector file is empty).
+- Timing windows are simplistic (3-second capture), potentially scriptable.
+
+Conclusion: stronger than basic checkbox CAPTCHA in *some* scripted-browser contexts, but weaker than modern risk engines + telemetry stacks against determined adversaries.
+
+## 5) Scalability and performance
+- Current app is synchronous-heavy around OpenCV processing with per-request temp file writes.
+- No task queue (Celery/RQ/Kafka) for video processing offload.
+- SQLite default DB in code path is not suitable for high concurrency production.
+- In-memory rate limiter/session stores do not scale horizontally.
+
+For 10k+ daily verifications: feasible with careful tuning.
+For 100k–1M: requires architectural redesign (object storage + async workers + distributed cache + managed DB + autoscaling).
+
+## 6) Data/privacy posture
+- System handles face video (biometric-adjacent/sensitive data) but retention/deletion policies are not strongly encoded in code-level lifecycle controls.
+- Logs may capture detailed verification metadata and potentially sensitive behavior traces.
+- No visible consent artifact/version binding in verification transaction records.
+
+GDPR readiness today: likely insufficient without explicit lawful basis flows, DSR tooling, retention enforcement, and DPIA-grade controls.
+
+## 7) Product/UX review
+Pros:
+- Guided multi-screen flow is understandable.
+- Fast-track concept (trusted devices get easier flow) is good UX framing.
+
+Cons:
+- Hardcoded API URL breaks non-local deployments.
+- 3-second fixed recording can fail for accessibility/language/device variance.
+- Potentially high failure frustration if camera quality/lighting is weak.
+
+## 8) DevOps/deployment readiness
+Good signs:
+- Nginx/systemd scripts present.
+- Prometheus and optional Sentry integrations exist.
+
+Gaps:
+- Environment split discipline is partial.
+- No clear container orchestration or worker topology for CV workloads.
+- CI quality gate appears limited to lightweight tests; integration tests rely on native libs that can fail in many environments.
+
+## 9) Code quality assessment
+Strengths:
+- Clear docstrings and readable flow.
+- Modular files for DB/challenge/verification/admin.
+
+Weaknesses:
+- Overloaded `main.py` (god file).
+- Security-critical logic mixed with presentation and comments that imply temporary toggles.
+- Some code paths look test-only or placeholder-like in production logic.
+- Inconsistency between documented architecture and actual enforcement.
+
+## 10) Competitive position
+### Unique angle
+- Visible, action-based human proof can be a differentiated UX in high-trust onboarding contexts.
+
+### Where it loses today
+- Against reCAPTCHA/Turnstile on risk intelligence scale and anti-abuse telemetry.
+- Against enterprise liveness vendors on anti-spoof rigor, certifications, and biometric risk controls.
+- Against attackers with commodity face animation/deepfake pipelines unless upgraded.
+
+## 11) VC-style assessment
+### Is it fundable now?
+- As-is: **pre-seed prototype quality**, not institutional-grade anti-bot security product.
+- Fundable only if positioned as an R&D wedge with clear roadmap and customer segment where video friction is acceptable.
+
+### Biggest risks
+1. Bypass economics: attacker cost may be too low.
+2. Privacy/regulatory overhead for biometric-like data.
+3. User drop-off from camera friction.
+4. Infra cost explosion if video processing scales before conversion proves out.
+5. Competitive moat erosion by larger anti-bot providers.
+
+### What could kill it
+- Public bypass PoC showing high pass rates.
+- Regulatory incident tied to facial/video handling.
+- Poor conversion from verification friction.
+
+### What makes it 10x better
+1. Move from heuristic-only to multimodal liveness + risk telemetry fusion.
+2. Introduce cryptographic challenge binding and replay-hard protocol design.
+3. Replace device_id trust with signed attestation + behavioral reputation.
+4. Build privacy-by-design controls (retention, encryption, minimization) as product primitives.
+5. Add enterprise integration surface (SDKs, policy engine, risk scoring API).
+
+## 12) Final verdict
+- **Brutal score (today): 4.5 / 10**
+
+### Top 5 critical issues
+1. Broken/disabled and non-distributed rate limiting.
+2. Weak replay/deepfake resistance.
+3. Client-spoofable identity/trust boundaries.
+4. Monolithic architecture with limited scale path.
+5. Insufficient privacy/compliance hardening for biometric-adjacent data.
+
+### Top 5 highest-impact improvements
+1. Security architecture rewrite: signed one-time challenges, strict nonce/timestamp binding, anti-replay proofs.
+2. Infrastructure split: API tier + async video workers + queue + object storage + Redis + Postgres.
+3. Detection hardening: active challenge randomization, phrase + motion combos, anti-spoof models.
+4. Risk engine fusion: device/browser/network behavioral telemetry, not only video heuristics.
+5. Compliance operating model: retention automation, encryption/KMS, audit trails, DSR tooling, policy controls.
