# ADR-0004: Programme-owned rules and charter

## Decision

Every programme defines its own charter, entity eligibility, minimum QSOs, activation validity, awards, exclusions, public-access policy, approver policy and content. MyOTA supplies schemas, lifecycle primitives, policy evaluation hooks and auditability; it does not copy or inherit the rules or charter of POTA, MPOTA, or another initiative.

The bundled MPOTA and Regional Outdoor Activation records are synthetic fixtures used to prove multi-programme behavior. They are not normative programme policy and must be replaced or versioned by the programme owner before production use.

## Consequences

- A programme configuration is versioned and referenced by activation/award decisions so historical results remain reproducible.
- Shared platform code may expose generic capabilities such as `minimumQsos`, but the values and interpretation belong to each programme.
- Import adapters must not decide programme eligibility; they only preserve source facts and provenance. Programme policy evaluates those facts.
- Product and legal review is required when onboarding a programme; onboarding is not a data copy operation.

