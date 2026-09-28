# Geodata production pipeline

The geodata service treats source facts, programme policy, and approval as separate concerns:

```text
source adapter -> normalized snapshot -> validation -> conflation candidates
       |                 |                    |              |
       +-- manifest -----+                    +--> review --> API-owned status
```

## Source adapters

Every import carries a source key, retrieval time, license, attribution, URL/format metadata, and a record-level source snapshot. Supported adapter codes are:

- `PARKSERVE_US`: ParkServe identifiers and licensed-source metadata are preserved without copying eligibility rules into the platform.
- `OSM`: only `leisure=park`, `leisure=nature_reserve`, `boundary=protected_area`, and `landuse=recreation_ground` records are admitted. OSM attribution and source references are retained.
- `GOVERNMENT_GIS`: the same adapter accepts normalized GeoJSON/WFS records, ArcGIS FeatureServer `rings`/`x,y` geometry, and records marked as Shapefile input. The source format remains in provenance so a dedicated fetch/decoder worker can be selected per authority.
- `MANUAL`: a drawn GeoJSON point/way/polygon enters as `CANDIDATE`; attachment metadata is validated and stored separately from source geometry. A proposal may select multiple shared entity categories, with the first category retained as the compatibility primary value.

All geometries are normalized to WGS84 (`EPSG:4326`). Web Mercator (`EPSG:3857`) is converted at the ingestion boundary. Geometry type, ring closure, coordinate bounds, coordinate count, feature count, and attachment size are bounded before persistence.

## Manifests, refresh, and disappearance

Each run creates an immutable source manifest with a source hash and per-record hashes. A refresh schedule records the programme, adapter, source metadata, interval, and disappearance policy. Complete snapshots can apply one of:

- `UNCHANGED`: retain the last state;
- `STALE`: retain lifecycle status but mark the source record stale;
- `REVIEW_REQUIRED`: retain lifecycle status and queue source disappearance for human review;
- `RETIRED`: retire the source entity while preserving historical references.

The default is `REVIEW_REQUIRED`. File and pasted imports first normalize into
durable `geodata_import_candidate` records and stop at `PREPROCESSED`. During
that step the service checks each normalized record against existing entity
geometry. Identical geometry or a centroid distance below 50 metres adds a
non-blocking `POSSIBLE_DUPLICATE` warning and comparison geometry; it never
silently merges or rejects a record. The admin web displays active runs in a
dedicated pre-processing queue, separate from Geodata Review, with pending and
confirmed candidate counts. The administrator validates a paged selection,
then a separate NATS-backed processing queue promotes confirmed records to an
explicitly selected `CANDIDATE` or `APPROVED` entity. Only then does a
candidate become visible to Geodata Review. An import run reports
pre-processed, promoted, skipped, invalid, disappeared, and conflation
records and is idempotent when an idempotency key is supplied.

The API surface is:

- `GET /v1/geodata/imports/{runId}/candidates` for compact paged validation;
- `GET /v1/geodata/imports` for run status and pending/confirmed/processed/rejected candidate counts;
- `POST /v1/geodata/imports/{runId}/candidates/validate` to confirm selected records;
- `POST /v1/geodata/imports/{runId}/process` to publish the selected promotion request to `myota.geodata.import.process.v1`.

The durable `geodata_import_processing_queue` table is the service-side
projection of the NATS request. Local development has a bounded fallback
worker; production consumers must preserve the same idempotency and explicit
target-status checks.

## Conflation

Potential duplicates are scored using source identifiers, normalized name similarity, bounding-box overlap, containment, centroid distance, and jurisdiction. Reviewers can choose `MERGED`, `KEPT_SEPARATE`, `IGNORED`, or reopen the candidate as `OPEN`. Every decision is append-only and reversible; no source record or approved entity is deleted by conflation.

## Spatial delivery and QGIS

`/v1/geodata/bbox` provides bounded GeoJSON for viewport queries and `/v1/geodata/tiles/{z}/{x}/{y}` provides a bounded vector-tile-compatible response. Both enforce response limits and expose a performance budget. PostGIS keeps GiST geometry/geography indexes for the production query path.

QGIS uses the read-only review/approved views and the editor role can write only to `geodata_edit_staging`. It cannot delete entities or approve lifecycle transitions. Geometry repairs are submitted back through the API, where approver scope, status invariants, audit history, and events remain authoritative.

The scheduler/control-plane endpoints are intentionally separate from network fetching. A deployment-specific importer worker fetches an authority’s WFS, GeoJSON, Shapefile, ArcGIS FeatureServer, ParkServe, or OSM extract, validates its license/allowlist, then submits the normalized snapshot to the service. Imports are programme-independent; programme assignment is a later eligibility decision.

The relational assignment table `geodata_entity_category` is introduced by
`008_entity_category_assignments.sql`. `geodata_entity.entity_type_code`
remains the primary compatibility column, while the relation stores every
shared category assigned to the entity. The geodata service migration is
canonical; platform and deployment copies are synchronized mirrors.
