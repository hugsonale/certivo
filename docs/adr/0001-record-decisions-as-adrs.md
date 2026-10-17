# ADR 0001: Record decisions as ADRs

- **Date:** 2026-10-09
- **Status:** Accepted
- **Decision register / step IDs:** P0-02

## Context

Certivo is built by a very small team from an 18-document specification suite that was written from ideas. Several parts of the suite will change as we build and test. Without a written trail, we would forget why choices were made and could not tell a deliberate change from a mistake.

## Options considered

1. **Keep decisions in chat or memory:** quick, but lost over time.
2. **Edit the specification documents only:** shows the latest state but not the reasoning.
3. **One short ADR per significant decision, plus updating the affected document:** a little extra writing, and a durable record.

## Decision

Use option 3. Each significant decision gets an ADR in `docs/adr/`. When an ADR changes what a specification document says, the document is updated in the same pull request.

## Consequences

A few minutes of writing per decision. The decision register in the Master Build Guide links to ADRs. Reviewers can ask "where is the ADR?" for any hard-to-reverse change.
