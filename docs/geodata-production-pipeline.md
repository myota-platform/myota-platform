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
- `MANUAL`: a drawn GeoJSON point/polygon/multipolygon enters as `CANDIDATE`; attachment metadata is validated and stored separately from source geometry.

All geometries are normalized to WGS84 (`EPSG:4326`). Web Mercator (`EPSG:3857`) is converted at the ingestion boundary. Geometry type, ring closure, coordinate bounds, coordinate count, feature count, and attachment size are bounded before persistence.

## Manifests, refresh, and disappearance

Each run creates an immutable source manifest with a source hash and per-record hashes. A refresh schedule records the programme, adapter, source metadata, interval, and disappearance policy. Complete snapshots can apply one of:

- `UNCHANGED`: retain the last state;
- `STALE`: retain lifecycle status but mark the source record stale;
- `REVIEW_REQUIRED`: retain lifecycle status and queue source disappearance for human review;
- `RETIRED`: retire the source entity while preserving historical references.

The default is `REVIEW_REQUIRED`. An import run reports created, updated, skipped, invalid, disappeared, and conflation records and is idempotent when an idempotency key is supplied.

## Conflation

Potential duplicates are scored using source identifiers, normalized name similarity, bounding-box overlap, containment, centroid distance, and jurisdiction. Reviewers can choose `MERGED`, `KEPT_SEPARATE`, `IGNORED`, or reopen the candidate as `OPEN`. Every decision is append-only and reversible; no source record or approved entity is deleted by conflation.

## Spatial delivery and QGIS

`/v1/geodata/bbox` provides bounded GeoJSON for viewport queries and `/v1/geodata/tiles/{z}/{x}/{y}` provides a bounded vector-tile-compatible response. Both enforce response limits and expose a performance budget. PostGIS keeps GiST geometry/geography indexes for the production query path.

QGIS uses the read-only review/approved views and the editor role can write only to `geodata_edit_staging`. It cannot delete entities or approve lifecycle transitions. Geometry repairs are submitted back through the API, where approver scope, status invariants, audit history, and events remain authoritative.

The scheduler/control-plane endpoints are intentionally separate from network fetching. A deployment-specific importer worker fetches an authority’s WFS, GeoJSON, Shapefile, ArcGIS FeatureServer, ParkServe, or OSM extract, validates its license/allowlist, then submits the normalized snapshot to the service.
