# Source inspection: `ea7klk/mpota`

The source repository was inspected through its public GitHub tree, README/charter, and the architecture README. It is an architecture and runnable-MVP foundation rather than a completed service implementation. The relevant source decisions include:

- public map results are approval-filtered;
- country/continent/all-country approver scopes are explicit;
- proposals remain pending until authorized approval;
- ADIF ingestion is asynchronous and auditable;
- the source architecture includes awards, translations, RBAC, tile lifecycle and OpenAPI;
- the source deliberately omits POTA-specific early/late shift concepts;
- source activation validity uses a five-valid-QSO threshold in its current MPOTA design.

MyOTA carries these as migration concerns and generic platform capabilities, not as inherited rules. In particular, the sample programme in this repository uses synthetic configuration and a different activation threshold; no POTA charter, rules, award definitions or eligibility policy were copied. Each future programme must provide its own versioned policy and charter.

