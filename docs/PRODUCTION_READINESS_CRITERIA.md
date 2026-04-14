# Certivo Production-Readiness Criteria

**Version:** 1.0  
**Last updated:** 2026-04-06  
**Audience:** Engineering, Security, Product, Compliance, DevOps, Leadership

---

## 0) Purpose and Definition of Done

This document translates the deep audit findings into a measurable production-readiness program.

> **Production-ready for Certivo** means: the platform is secure against common and advanced bypass attempts, legally defensible for biometric-adjacent processing, operationally reliable at scale, and commercially usable with acceptable user friction and cost.

### Exit Gate (must all be true)
- No known **Critical** or **High** severity security issues open in the release scope.
- Independent red-team bypass success rate below threshold defined in §4.8.
- SLOs in §6.1 met for 30 consecutive days in staging-like load and 14 days in production.
- Privacy/compliance controls in §7 pass legal review with auditable evidence.
- Recovery objectives (RTO/RPO) tested and met.
- Incident response runbook exercised and signed off.

---

## 1) Priority Framework

### Severity Levels
- **P0/Critical:** Breach, easy bypass at scale, major legal exposure, or sustained outage risk.
- **P1/High:** Significant exploitability or reliability issues with material business impact.
- **P2/Medium:** Important but non-blocking before initial production launch.
- **P3/Low:** Improvement/backlog.

### Delivery Tracks
- **Track A (P0 Security Foundation)**
- **Track B (Scalable Architecture)**
- **Track C (Privacy & Compliance)**
- **Track D (Product/UX Conversion)**
- **Track E (Operational Excellence)**

---

## 2) Current Critical Gaps (from audit) to close before launch

1. Rate limiting inconsistencies and disabled controls in challenge path.  
2. Weak anti-replay and weak challenge-response cryptographic binding.  
3. Heuristic-only liveness insufficient against deepfake/pre-recorded attacks.  
4. Client-spoofable identity boundaries (device ID trust and fallback trust paths).  
5. Monolithic request path for video processing (no resilient queue/worker architecture).  
6. SQLite/non-distributed runtime patterns not suitable for high concurrency.  
7. Sensitive-data lifecycle and deletion/retention controls not fully enforceable.  
8. Admin/security telemetry exposure risks and incomplete hardening.

---

## 3) Production Architecture Criteria

### 3.1 Service Topology (Required)
- API Gateway / Edge (WAF + DDoS + bot heuristics + TLS termination).
- Verification API service (stateless, horizontally scalable).
- Challenge service (nonce generation + one-time challenge lifecycle).
- Async processing pipeline (queue + worker pools).
- Risk scoring service (fusion of liveness, behavior, device, reputation).
- Admin service isolated behind strong authz and network controls.
- Object storage for video and evidence artifacts.
- Redis (rate limiting, one-time tokens, ephemeral state).
- Postgres (transactional truth data).

**Acceptance criteria**
- Any service can scale independently (HPA or equivalent).
- No critical runtime dependency on in-memory local process state.
- All inter-service traffic authenticated and encrypted.

### 3.2 API Design Standards
- `/v1` versioning retained; no breaking changes without version bump.
- OpenAPI spec complete and generated from source-of-truth.
- Consistent error schema with typed error codes.
- Idempotency keys for endpoints with retriable side effects.

**Acceptance criteria**
- 100% public endpoints documented in OpenAPI.
- API contract tests pass in CI on every merge.

### 3.3 Challenge-Verify-Finalize Integrity Model
- Challenge issuance returns signed token containing: `challenge_id`, nonce, expiry, allowed actions, one-time-use flag.
- Verify accepts only active, unconsumed challenge tokens.
- Finalize consumes verification result via server-side persisted proof only (never trust client-computed results as source of truth).

**Acceptance criteria**
- Replay attempts with same challenge token fail 100%.
- Expired challenge usage rejected 100% with deterministic error code.

---

## 4) Security and Anti-Abuse Criteria (Launch Blocking)

### 4.1 Rate Limiting and Abuse Controls
- Multi-dimensional limits: IP, subnet, ASN, device fingerprint, account, session, challenge ID.
- Distributed enforcement via Redis + edge WAF.
- Progressive penalties: soft throttle -> hard block -> temporary ban.

**Acceptance criteria**
- Limits remain correct under 3+ API replicas.
- Bypass attempts via simple IP rotation increase attacker cost measurably (tracked metric).

### 4.2 Challenge Entropy and Predictability
- Expand challenge space from finite simple gestures to combinatorial multi-step challenges.
- Server-side randomness from cryptographically secure RNG.
- Challenge templates rotated and A/B hardened.

**Acceptance criteria**
- Effective challenge entropy target: >= 20 bits per session equivalent (documented method).
- Static prerecorded video attack success < 1% in red-team suite.

### 4.3 Replay Resistance and Cryptographic Binding
- Signed JWT/PASETO challenge token with short TTL.
- Bind capture session metadata to challenge nonce.
- One-time consume semantics in Redis/Postgres transaction.
- Optional frame watermark and/or dynamic prompt overlays tied to nonce.

**Acceptance criteria**
- Token tamper detection 100%.
- Reuse of prior valid payload fails 100%.

### 4.4 Liveness and Deepfake Resistance
- Move from heuristics-only to multi-signal model:
  - Motion trajectory consistency
  - Temporal landmarks
  - Audio phrase challenge + lip sync consistency
  - Spoof detection model (screen replay/deepfake artifacts)
  - Optional device camera attestation where available

**Acceptance criteria**
- Deepfake/red-team success rate below threshold (<5% initial target, ratchet down quarterly).
- False rejection rate (FRR) and false acceptance rate (FAR) monitored and within policy.

### 4.5 Input Validation and API Hardening
- Strict request schema validation.
- File upload MIME/content sniffing and size constraints.
- Antivirus/sandbox checks as needed.
- SQLAlchemy parameterized access only; no raw interpolated SQL.

**Acceptance criteria**
- SAST/DAST critical findings: 0.
- Upload abuse tests (polyglot/malformed files) pass.

### 4.6 Authentication and Authorization
- Admin endpoints require strong authentication (MFA) and role-based authorization.
- Privileged actions audited with immutable log trail.
- Session security: secure cookies or signed bearer with rotation and revocation.

**Acceptance criteria**
- Unauthorized access tests for admin endpoints: 100% blocked.
- Privilege escalation test cases: 0 passes.

### 4.7 Secrets and Key Management
- Secrets in vault/KMS, never in source code.
- Key rotation policies and emergency rotation runbook.
- Per-environment credentials isolated.

**Acceptance criteria**
- Secret scan in CI has zero high-confidence exposures.
- Rotation drill performed successfully before launch.

### 4.8 Red-Team Program (Mandatory)
- External/internal adversarial tests include:
  - Replay attacks
  - Video injection
  - Headless automation
  - Prompt prediction and challenge farming
  - Device spoofing

**Acceptance criteria**
- Define and enforce risk gate: e.g., weighted bypass success score < 0.05 for launch.
- Findings tracked with SLA: P0 24h, P1 7d.

---

## 5) Verification Logic Criteria

### 5.1 Challenge Design
- Support composite prompts (e.g., turn left -> blink twice -> read random digits).
- Accessibility-aware alternatives (motor/vision/speech constraints).
- Locale-aware prompts.

**Acceptance criteria**
- At least 12 challenge templates live at launch.
- Completion rate > 85% for legitimate users in pilot cohort.

### 5.2 Timing and Session Controls
- Strict challenge TTL and attempt caps.
- Server time as only authority for expiry.

**Acceptance criteria**
- Brute force via repeated retries materially constrained (quantified in abuse dashboard).

### 5.3 Risk Scoring
- Weighted score from liveness, behavior, device, network reputation.
- Policy engine for per-customer thresholds.

**Acceptance criteria**
- Policy changes deploy without code changes.
- Explainability record available for every denial/flag.

---

## 6) Scalability, Reliability, and Performance Criteria

### 6.1 SLOs
- API availability: 99.9% monthly.
- P95 challenge issuance latency: <= 300 ms.
- P95 verify accept latency (excluding upload transfer): <= 2.5 s.
- Queue processing delay P95: <= 5 s under normal load.

### 6.2 Capacity Targets
- Demonstrate sustained support at:
  - **Phase 1:** 10k verifications/day
  - **Phase 2:** 100k/day
  - **Phase 3:** 1M/day (with regional scaling)

**Acceptance criteria**
- Load tests with realistic video payload distributions.
- No single-node bottleneck (DB, queue, object store throughput validated).

### 6.3 Async Pipeline
- Upload -> object storage -> enqueue job -> worker analysis -> results store -> callback/poll result.
- Retries with poison queue and dead-letter handling.

**Acceptance criteria**
- Worker failure does not lose job data.
- End-to-end exactly-once/at-least-once semantics documented and tested.

### 6.4 Data Stores
- Postgres HA (backups, PITR).
- Redis HA for ephemeral state.
- TTL policies for transient artifacts.

**Acceptance criteria**
- Backup restore test successful.
- RPO <= 15 minutes, RTO <= 1 hour (or agreed business target).

---

## 7) Data Governance, Privacy, and Compliance Criteria

### 7.1 Data Classification
- Label all fields: public/internal/sensitive/biometric-adjacent.
- Data inventory maintained with owner and retention.

### 7.2 Retention and Deletion
- Configurable retention windows by tenant/jurisdiction.
- Automatic deletion jobs with audit trail.
- User/tenant erasure workflow.

**Acceptance criteria**
- Deletion request completed within policy SLA (e.g., <=30 days).
- Deletion is verifiable in logs and storage checks.

### 7.3 Legal and Consent
- Explicit consent capture for video/liveness where required.
- Purpose limitation and minimization documented.
- DPIA/PIA completed prior to broad rollout.

### 7.4 Security of Sensitive Data
- Encryption in transit (TLS1.2+) and at rest (KMS-managed keys).
- Access control least privilege with periodic review.

**Acceptance criteria**
- Quarterly access review complete.
- No broad wildcard storage access in production roles.

### 7.5 Compliance Readiness (Principle Level)
- GDPR/CCPA-aligned workflows:
  - access, correction, deletion, portability, objection where applicable.
- Processor/subprocessor register maintained.

---

## 8) UX and Product Criteria

### 8.1 Friction Management
- Time-to-complete target <= 20 seconds median for successful users.
- Progressive trust: lower-friction path for low-risk events, stronger checks for high-risk events.

### 8.2 Clarity and Accessibility
- Clear real-time guidance during capture.
- Fallback path when camera/mic unsupported.
- WCAG-informed UI improvements.

### 8.3 Mobile and Device Coverage
- Verified support matrix for major browsers/OS.
- Degrade gracefully for weak network and low-end devices.

**Acceptance criteria**
- Funnel metrics instrumented: start, permissions granted, upload started, verified, abandoned.
- Drop-off per stage reviewed weekly post-launch.

---

## 9) DevOps, Observability, and Release Criteria

### 9.1 Environment Strategy
- Separate dev/staging/prod with isolated credentials and data.
- Infrastructure as code for reproducibility.

### 9.2 CI/CD
- Required checks: unit, integration, contract, security scans, migration checks.
- Signed artifacts and provenance metadata where feasible.

### 9.3 Observability
- Structured logs with correlation IDs.
- Metrics: FAR/FRR, bypass attempts, queue lag, error budget burn.
- Tracing for challenge->verify->finalize path.

### 9.4 Incident Management
- On-call rotation + runbooks.
- Severity matrix and communication templates.
- Postmortem process with corrective action tracking.

**Acceptance criteria**
- Synthetic probes for critical endpoints.
- At least one game-day simulation completed before GA.

---

## 10) Code Quality and Engineering Standards

### 10.1 Architecture Hygiene
- Break monolith orchestration into domain modules/services.
- Shared libraries for validation, authz, telemetry, error handling.

### 10.2 Quality Gates
- Unit test coverage target >= 80% in critical services.
- Integration tests for full verification flow.
- Security tests integrated into CI.

### 10.3 Documentation
- ADRs for major architecture/security decisions.
- Runbooks for deployment, rollback, key rotation, and incident response.

**Acceptance criteria**
- New critical code paths require tests + docs as merge requirement.

---

## 11) Competitive Readiness Criteria

To compete with reCAPTCHA/Turnstile/liveness vendors, Certivo must demonstrate:
- Comparable abuse resistance for target threat model.
- Better explainability and policy control for enterprise buyers.
- Clear differentiation in trust-sensitive workflows (not generic low-friction captcha replacement).

**Acceptance criteria**
- Benchmark report against at least 2 alternatives on:
  - bypass resilience
  - user completion rate
  - latency
  - cost per 1k verifications

---

## 12) Business and Investor Readiness Criteria

### 12.1 Moat and Defensibility
- Proprietary risk signals and anti-spoof datasets.
- Continuous learning loop from attack telemetry.
- Integration ecosystem (SDKs, policy APIs, dashboards).

### 12.2 Unit Economics
- Cost model by verification type and region.
- Gross margin target and scaling assumptions.

### 12.3 Go-To-Market Readiness
- ICP-defined use cases (high-risk onboarding, payout protection, account recovery).
- Customer security/compliance packet for enterprise procurement.

**Acceptance criteria**
- Pilot customers with measurable fraud reduction and acceptable conversion impact.

---

## 13) 90-Day Execution Plan (Suggested)

### Phase 1 (Days 0-30): Security Foundation
- Reinstate/fix distributed rate limiting and endpoint hardening.
- Implement signed one-time challenge tokens and strict finalize semantics.
- Lock down admin endpoints + MFA + RBAC.
- Establish abuse telemetry dashboards.

### Phase 2 (Days 31-60): Scalable Core
- Move verification to async queue/worker architecture.
- Introduce object storage lifecycle policies.
- Migrate/validate production Postgres + Redis HA setup.
- Complete realistic load testing at 10k/day and 100k/day targets.

### Phase 3 (Days 61-90): Product + Compliance + Red Team
- Ship improved composite challenge set + accessibility variants.
- Implement retention/deletion automation and compliance workflows.
- Execute adversarial red-team program and close P0/P1 findings.
- Final launch readiness review against this checklist.

---

## 14) Readiness Scorecard Template

Use a binary + maturity score for each criterion:
- **Status:** Not Started / In Progress / Done / Verified
- **Evidence:** PRs, dashboards, test reports, legal signoff, runbook links
- **Owner:** Eng/Sec/Product/DevOps/Legal
- **Target Date**
- **Risk if missed**

### Minimum launch score recommendation
- 100% of P0 criteria = Verified
- >= 90% of P1 criteria = Verified
- No unmitigated legal/security blocker

---

## 15) Non-Negotiable “Do Not Launch Without” List

1. Distributed rate limiting and anti-abuse controls are live and verified.  
2. Challenge-response protocol is cryptographically bound, short-lived, and one-time consumable.  
3. Final trust decision does not rely on client-provided unverifiable data paths.  
4. Admin surface is protected by strong authn/authz and audited.  
5. Async resilient processing pipeline exists for video workloads.  
6. Data retention/deletion controls are implemented and testable.  
7. Red-team bypass tests pass launch threshold.  
8. Incident response and recovery drills completed

---

## 16) “100%” Clarification

No security product is permanently 100% attack-proof. The practical goal is **production-grade risk management**: layered controls, measurable resilience, rapid detection/response, and continuous hardening.

This checklist defines the minimum bar for Certivo to be considered production-ready in that realistic sense.
