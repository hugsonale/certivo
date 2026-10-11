# Quarterly Access Review Checklist

**Quarter:** Q[X] [YEAR]  
**Review Date:** [DATE]  
**Reviewed By:** [NAME]

## Pre-Review

- [ ] Generate review report: `python scripts/generate_access_review.py`
- [ ] Export user list to spreadsheet
- [ ] Schedule review meeting with stakeholders

## Review Process

For each user with access:

- [ ] User still employed? (Yes/No)
- [ ] Access still needed for job function? (Yes/No)
- [ ] Business justification still valid? (Yes/No)
- [ ] No wildcard permissions? (Verify/No)
- [ ] Last activity within 90 days? (Yes/No)

**Decision:**
- [ ] Approve (continue access)
- [ ] Revoke (remove access)
- [ ] Modify (change role/permissions)

## Wildcard Check

- [ ] Run wildcard validation: `python scripts/validate_no_wildcards.py`
- [ ] Result: No violations found (Yes/No)
- [ ] If violations: Document and remediate

## Post-Review

- [ ] Update access in system
- [ ] Send notifications to users
- [ ] File review report in records
- [ ] Schedule next review (90 days)

## Sign-Off

**Reviewer:** ________________  
**Date:** ________________  
**Next Review:** ________________