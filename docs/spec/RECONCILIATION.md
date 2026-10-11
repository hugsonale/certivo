# Reconciliation record (build step P0-05)

## What this is

The 18-document suite repeatedly relies on a "Version 1.0" ("unchanged from Version 1.0", "the existing policy
engine", "Version 1.0's error schema"). **That version never existed**; the suite grew from ideas. So there
was nothing to reconcile *against*. Instead, for every place the suite leans on a missing base, this record
says how we settled it. The new definitions are in `docs/spec/base/`.

| Word | Meaning |
|---|---|
| **Aligned** | We follow the suite as written |
| **Defined** | The suite assumed it existed; we wrote it (see the linked document) |
| **Changed** | We deliberately differ from the suite; an ADR explains why |
| **Deferred** | Not needed for the flagship yet; the named build step will define it |

## A. The eight resource groups the API Specification calls "unchanged from v1"

| v1 resource group | Result | Where | ADR | Built in |
|---|---|---|---|---|
| Verifications (point-in-time) | **Deferred**. Never specified; written from scratch for the retained verticals | none yet | none | P2-06, P2-07 |
| Policies | **Defined** (with changes: effective confidence, `fallback_behavior`, visibility) | base/03 | 0008 | Basic implemented; P0-11 |
| Attestations and keys | **Aligned** with the suite and Build Spec 0 section 8; rotation **Defined** | base/02 section 5 | 0007 | Basic implemented; P0-10 |
| Authentication | **Defined** | base/02 | 0007 | Basic implemented; P0-06 |
| Webhooks | **Defined** | base/05 | 0010 | Outbox implemented; P0-07 |
| Privacy and consent | **Defined** | base/04 | 0009 | P0-51 |
| Analytics and audit logs | **Defined** | base/06 | 0011 | P0-13, P1-11 |
| Error code reference | **Defined** and implemented, enforced by tests | base/01 | 0006 | Implemented |

## B. The `[reconcile]` markers in Build Spec 0

| Marker | Result |
|---|---|
| Header note: v1 resource groups, error codes and policy engine "not in the uploaded set" | **Settled.** They never existed; replaced by pointers to `base/` and this record |
| Section 2: error codes "[reconcile] with Doc 6's v1 error-code reference" | **Settled.** Full catalogue in base/01, kept equal to the code by a test |
| Section 11, item 4: "v1 documents. Send them" | **Settled.** Resolved here; one new decision (D-17) came out of it |

## C. Other places the suite leans on a missing "v1" or "existing" part

| Where the suite says it | What it assumed | Result | Notes |
|---|---|---|---|
| TRD section 13 | "REST conventions, versioning, and the standard error schema apply unchanged" | **Defined** | base/01 |
| System Design Doc, section 4 | A policy engine "unchanged" from point-in-time, applied per interval | **Defined** | base/03. No point-in-time engine exists; this one is per interval from the start |
| TRD component table (Notification Service) | Webhook delivery "unchanged", gaining new event types | **Defined** | base/05 |
| Privacy Architecture, section 1 and Table 1 | A Privacy and Consent Service persisting wording versions and timestamps | **Defined** | base/04 |
| System Design Doc, Figure 5.1 | An Analytics Service receiving telemetry events | **Defined** | base/06 |
| Security Architecture, "unchanged" controls | Rate limiting, RBAC, audit logging, OWASP alignment | **Deferred** in parts | Rate limits P0-06; audit P0-13; OWASP checklist P0-61; dashboard roles P1-11 |
| Security Architecture, section 4.2 | "Version 1.0's key rotation procedure" for Certivo's own signing keys | **Defined** | base/02 section 5; built in P0-10 |
| Security Architecture, section 6.4 (referenced by the TRD) | Rate-limit and anomaly logic | **Deferred** | P0-06 and P0-12 |
| Privacy Architecture, Table 3.1 | A retention period for session attestations | **Deferred** | A legal and privacy-review decision (P0-52). No number invented |
| TRD Table 8.1, Tier 3 | A "Device Trust Service" supplying fingerprint and behavioural signals | **Changed** | No such service exists and fingerprinting is itself a privacy risk. Tier 3 now means only "a registered software-held key". ADR 0007 |
| Database Design, section 2.2 | Revised `verification_sessions` "additions only" to a base table | **Deferred** | The base table never existed; defined with the verticals (P2-06) |
| DevOps Manual, sections 10.4, 11.1 and Table 7.1 | A single-approver promotion, a canary pattern and backup tiers | **Deferred** | Defined with the first production environment (P1-17, P1-22) |
| ML Architecture and AI Research, base sections | The base model pipeline and a whole-clip temporal analysis | **Deferred** | Built in P0-30 to P0-40 |
| Design System and UX Specification, base sections | Colour, type, spacing, error and loading states, mobile and desktop guidance | **Deferred** | P0-50 and P0-51 |
| PRD sections 6.3 to 6.7 | Point-in-time functional requirements "carried forward" | **Deferred** | Re-examined when the verticals start (P2-06, P2-07) |

## D. Gaps the work uncovered

| Gap | What we did |
|---|---|
| **D-17 (new).** PRD FR-C.4 says participants receive each other's trust score, but nothing says how a participant's app receives it | **Proposed** in base/03 section 5: a `peers` endpoint with a partner-set visibility level. Needs your decision |
| A partner CI "sandbox" with deterministic server responses (PRD FR-6.3) | Today a client-side script simulates calls. A server-side test mode is **Deferred** to P1-12 |
| Unexpected crashes returned a plain-text 500 instead of the standard error shape | **Fixed now**: every error uses the envelope (`internal_error`), with a test |
| Nothing ties a face to a verified profile | Unchanged. Still decision D-03 |
| Voice-clone detection is mentioned (FR-C.1) but no model is designed | Unchanged. Still decision D-08 |

## E. Summary

- **Eight resource groups:** six defined, one aligned (attestations and keys), one deferred (verifications).
- **Three markers in Build Spec 0:** all settled.
- **Fifteen other dependencies on a missing "v1" part:** six defined, one changed (Tier 3), eight deferred to
  named build steps.
- **One new decision:** D-17 (how participants' apps receive each other's status).
- **One bug fixed:** unexpected crashes now use the standard error shape.
- Six ADRs (0006 to 0011) record the choices, and an automated test keeps everything marked **Implemented** in
  the base specifications equal to what the code actually does.
