# Data Protection Impact Assessment (DPIA)
## Certivo Human Verification System

**Document Version:** 1.0  
**Assessment Date:** [TO BE FILLED]  
**Next Review Date:** [TO BE FILLED - Annually or before major changes]  
**Prepared By:** [TO BE FILLED - Your Name/Title]  
**Reviewed By:** [TO BE FILLED - DPO Name/Title]  
**Approved By:** [TO BE FILLED - Management Name/Title]

---

## INSTRUCTIONS FOR COMPLETION

⚠️ **This is a TEMPLATE that YOU must complete before production rollout.**

**Who Should Complete This:**
- Legal/Compliance Team
- Data Protection Officer (DPO)
- Engineering Leadership
- Security Team

**When to Complete:**
- ✅ **NOW** - Before broad production rollout
- ✅ Before processing EU citizen data
- ✅ Before any major system changes
- ✅ Annually (ongoing reviews)

**How to Use This Template:**
1. Fill in all sections marked [TO BE FILLED]
2. Review with your legal team
3. Get DPO sign-off
4. Get management approval
5. Document in company records
6. Update annually or when system changes

---

## 1. PROJECT DESCRIPTION

### 1.1 System Overview

**Project Name:** Certivo Human Verification System

**Purpose:** [TO BE FILLED - Describe your business purpose]

Example: "Provide real-time human verification services to prevent bot abuse and fraudulent account access for our B2B customers."

**Scope:** [TO BE FILLED - Describe scope of deployment]

Example: "Global deployment serving customers in EU, US, UK, Canada, and Australia."

---

### 1.2 Data Processing Activities

**What Data is Collected:**

| Data Type | Category | Purpose | Legal Basis |
|-----------|----------|---------|-------------|
| Video of user face | Biometric-adjacent | Liveness detection | Consent + Legitimate Interest |
| Facial movement patterns | Biometric-adjacent | Bot detection | Consent + Legitimate Interest |
| Device fingerprint | Personal data | Fraud prevention | Legitimate Interest |
| IP address | Personal data | Fraud prevention | Legitimate Interest |
| Verification scores | Sensitive data | Identity verification | Consent |

[TO BE FILLED - Add/modify based on your actual data collection]

---

### 1.3 Data Subjects

**Who is Affected:**
- [TO BE FILLED] End users of customer systems
- [TO BE FILLED] Geographic regions: EU, US, UK, etc.
- [TO BE FILLED] Age ranges: 18+ (specify if serving minors)
- [TO BE FILLED] Vulnerable groups: None identified / [Specify if any]

---

## 2. NECESSITY AND PROPORTIONALITY

### 2.1 Is Processing Necessary?

**Can we achieve our purpose without this data?**

[TO BE FILLED - Justify each data type]

Example:
"✅ Video capture: NECESSARY - Cannot perform liveness detection without facial video  
✅ Device fingerprint: NECESSARY - Critical for fraud prevention  
❌ User's full browsing history: NOT NECESSARY - Removed from scope"

---

### 2.2 Data Minimization

**What data did we decide NOT to collect?**

[TO BE FILLED - Document what you intentionally excluded]

Example:
"- ❌ Full face biometric template (not needed - we only extract movement patterns)
- ❌ Audio recording (not needed for liveness detection)
- ❌ Geolocation beyond country-level (not needed)
- ❌ User browsing history (not needed)"

---

## 3. RISKS TO DATA SUBJECTS

### 3.1 Identified Risks

**Risk Matrix:**

| Risk | Likelihood | Impact | Severity | Mitigation |
|------|------------|--------|----------|------------|
| Unauthorized video access | Low | High | Medium | KMS encryption, access controls |
| Re-identification from movement patterns | Low | Medium | Low | No facial templates stored, 90-day retention |
| Data breach | Low | High | Medium | Encryption, quarterly access reviews |
| Consent confusion | Medium | Low | Low | Clear consent UI, multi-language |
| Discriminatory outcomes | Low | Medium | Low | Explainability, appeal process |

[TO BE FILLED - Assess risks specific to your deployment]

**Risk Scoring:**
- Likelihood: Low / Medium / High
- Impact: Low / Medium / High
- Severity: Low / Medium / High / Critical

---

### 3.2 Risk Mitigation Measures

**Technical Measures:**

[TO BE FILLED - Document YOUR actual implementations]

✅ Encryption in transit: TLS 1.2+  
✅ Encryption at rest: AWS KMS-managed keys  
✅ Access control: RBAC with quarterly reviews  
✅ Data retention: Automatic deletion after 90 days  
✅ Consent management: Explicit opt-in with withdrawal option  

**Organizational Measures:**

[TO BE FILLED - Document YOUR policies]

✅ Regular security audits: [Frequency]  
✅ Staff training: [Frequency and topics]  
✅ Incident response plan: [Status]  
✅ DPO appointed: [Yes/No - Name]  

---

## 4. CONSULTATION

### 4.1 Stakeholder Consultation

**Who was consulted:**

[TO BE FILLED - Document consultations]

| Stakeholder | Date | Key Concerns | Resolution |
|-------------|------|--------------|------------|
| Data Protection Officer | [Date] | [Concerns] | [How addressed] |
| Legal Team | [Date] | [Concerns] | [How addressed] |
| Security Team | [Date] | [Concerns] | [How addressed] |
| Customer Representatives | [Date] | [Concerns] | [How addressed] |

---

### 4.2 Data Subject Input

**Did we consult data subjects?**

[TO BE FILLED - Yes/No and how]

Example:
"✅ Yes - Conducted user survey with 100 participants
❌ No - Not required for B2B service / [Other reason]"

---

## 5. COMPLIANCE ASSESSMENT

### 5.1 GDPR Compliance (if processing EU data)

**Article 5 - Principles:**

| Principle | Compliant? | Evidence |
|-----------|------------|----------|
| Lawfulness, fairness, transparency | [✅/❌] | [Explain how] |
| Purpose limitation | [✅/❌] | [Explain how] |
| Data minimization | [✅/❌] | [Explain how] |
| Accuracy | [✅/❌] | [Explain how] |
| Storage limitation | [✅/❌] | [Explain how] |
| Integrity and confidentiality | [✅/❌] | [Explain how] |
| Accountability | [✅/❌] | [Explain how] |

[TO BE FILLED - Assess each principle]

---

**Article 9 - Special Categories (if applicable):**

[TO BE FILLED - If processing biometric data]

"⚠️ We process biometric-adjacent data (facial movement patterns).
✅ Legal basis: Explicit consent (Article 9(2)(a))
✅ Additional safeguards: No facial templates stored, 90-day retention"

---

### 5.2 Other Regulations

**CCPA (California):** [TO BE FILLED - Compliant? How?]

**UK GDPR:** [TO BE FILLED - Compliant? How?]

**PIPEDA (Canada):** [TO BE FILLED - Compliant? How?]

**Other:** [TO BE FILLED - List any other applicable regulations]

---

## 6. DATA PROTECTION BY DESIGN

### 6.1 Technical Measures

**Built-in Protections:**

[TO BE FILLED - Document your implementations]

✅ **Encryption:** All sensitive data encrypted with KMS keys  
✅ **Access Control:** Least privilege with quarterly reviews  
✅ **Data Minimization:** Only collect what's needed for stated purpose  
✅ **Retention:** Automatic deletion after retention period  
✅ **Consent:** Explicit, granular, and withdrawable  

---

### 6.2 Default Settings

**Privacy by Default:**

[TO BE FILLED - Document default settings]

✅ Shortest retention period by default  
✅ Most restrictive access by default  
✅ Opt-in for all non-essential processing  
✅ Clear privacy notices before data collection  

---

## 7. ACCOUNTABILITY

### 7.1 Documentation

**Records Maintained:**

[TO BE FILLED - List your documentation]

✅ This DPIA  
✅ Data inventory (Part 7.1)  
✅ Consent records  
✅ Access review logs  
✅ Security audit reports  
✅ Data breach register  
✅ DPO correspondence  

---

### 7.2 Contracts

**Data Processing Agreements:**

[TO BE FILLED - List key contracts]

| Party | Role | Agreement Type | Status |
|-------|------|----------------|--------|
| AWS | Infrastructure | DPA | ✅ Signed |
| [Cloud Provider] | [Service] | DPA | [Status] |
| [Subprocessor] | [Service] | DPA | [Status] |

---

## 8. DECISION

### 8.1 DPIA Outcome

**Can we proceed with the processing?**

[TO BE FILLED BY DPO/LEGAL]

☐ **YES** - Risks are acceptable, safeguards are sufficient  
☐ **YES WITH CONDITIONS** - [Specify conditions]  
☐ **NO** - Risks too high, additional measures needed  
☐ **CONSULT SUPERVISORY AUTHORITY** - High risk remains  

**Justification:**

[TO BE FILLED - Explain the decision]

---

### 8.2 Action Plan

**Required Actions Before Launch:**

[TO BE FILLED - List any required actions]

| Action | Owner | Deadline | Status |
|--------|-------|----------|--------|
| [Action 1] | [Name] | [Date] | [Status] |
| [Action 2] | [Name] | [Date] | [Status] |

---

## 9. SIGN-OFF

### 9.1 Approval

**Prepared By:**

Name: [TO BE FILLED]  
Title: [TO BE FILLED]  
Date: [TO BE FILLED]  
Signature: ___________________

**Data Protection Officer Review:**

Name: [TO BE FILLED]  
Title: Data Protection Officer  
Date: [TO BE FILLED]  
Signature: ___________________  
Decision: [Approved / Approved with conditions / Rejected]

**Management Approval:**

Name: [TO BE FILLED]  
Title: [TO BE FILLED - CEO/CTO/etc.]  
Date: [TO BE FILLED]  
Signature: ___________________

---

## 10. REVIEW SCHEDULE

**Next Review Due:** [TO BE FILLED - 12 months from approval or before major changes]

**Trigger for Early Review:**
- ✅ Major system changes
- ✅ New jurisdictions added
- ✅ New data types collected
- ✅ Change in legal requirements
- ✅ Data breach incident
- ✅ Significant user complaints

---

## APPENDIX A: DATA FLOW DIAGRAM

[TO BE FILLED - Add diagram showing how data flows through your system]

Example:
User → Video Capture → Liveness Detection → Verification Result → Storage
↓                    ↓                    ↓                ↓
Consent          Encryption         Explainability     Auto-deletion

---

## APPENDIX B: THIRD-PARTY PROCESSORS

[TO BE FILLED - List all third parties processing data]

| Processor | Service | Data Shared | Location | DPA Status |
|-----------|---------|-------------|----------|------------|
| AWS | Infrastructure | All | US/EU | ✅ Signed |
| [Other] | [Service] | [Data] | [Location] | [Status] |

---

## APPENDIX C: CONTACT INFORMATION

**Data Protection Officer:**

Name: [TO BE FILLED]  
Email: dpo@[your-company].com  
Phone: [TO BE FILLED]

**Privacy Inquiries:**

Email: privacy@[your-company].com

**Data Subject Requests:**

Email: dsr@[your-company].com  
Web Form: https://[your-company].com/privacy/request

---

**END OF DPIA TEMPLATE**