# ADR-0003: Four domain services and one deployment repository

The first split is identity, programme, geodata and activity. These boundaries match data ownership, security policy and scaling profile. A gateway/frontend is an edge concern, not a fifth domain service. Contracts and SDKs are versioned independently from service implementations. Helm and environment manifests live in a separate deployment repository.

The current bootstrap keeps these services together so a contributor can run the vertical slice without a multi-repository checkout. `docs/repository-map.md` is the extraction plan for the MyOTA GitHub organization.

