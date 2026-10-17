# Data Classification Policy

## Purpose
This policy defines how Certivo classifies, handles, and protects data.

## Classification Levels

### PUBLIC
- Definition: Data that can be freely shared
- Examples: API documentation, public blog posts
- Handling: No special requirements

### INTERNAL
- Definition: Business data for internal use only
- Examples: Session IDs, API metrics, challenge types
- Handling: Access restricted to employees

### SENSITIVE
- Definition: Data requiring protection due to PII or business sensitivity
- Examples: IP addresses, device IDs, risk scores, verification decisions
- Handling: 
  - Encryption at rest required
  - Access logging required
  - Limited access (need-to-know basis)

### BIOMETRIC-ADJACENT
- Definition: Data derived from biometric characteristics
- Examples: Liveness scores, motion scores, temporal scores
- Handling:
  - Encryption at rest and in transit required
  - Access logging required
  - Special consent requirements
  - Enhanced retention controls

## Data Owners

Each table must have:
- **Data Owner**: Business owner responsible for data quality and usage
- **Technical Owner**: Engineering owner responsible for infrastructure
- **Business Unit**: Department that owns the data

## Retention Policies

- **Short-term**: 7 days (challenges, temporary data)
- **Medium-term**: 90 days (sessions, verifications, risk assessments)
- **Long-term**: 7 years (explainability records, compliance audit trail)
- **Indefinite**: No automatic deletion (only if legally required)

## Review Schedule

All classifications must be reviewed:
- **Quarterly**: Biometric-adjacent and sensitive data
- **Annually**: Internal and public data