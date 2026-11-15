# Changelog

## Unreleased

### Breaking & Behavioral Changes

- **Metadata Store Path Encoding (`FileMetadataStore` / `FileArtifactStore`)**:
  - Path segments containing characters outside `[A-Za-z0-9._-]` (such as `:`, `/`, `*`, `?`, or `%`) are now percent-encoded (`host:3306` -> `host%3A3306`) instead of lossily replaced with `_`.
  - Existing legacy `_`-sanitized metadata files continue to be read transparently via fallback resolution and are automatically migrated (cleaned up) on the next `save_table_metadata` or `update_table_metadata` write.
  - To force an immediate migration and regenerate all Markdown/OKF exports cleanly, run `irides metadata export`.
- **Foreign Key Schema Enrichment & First Rescan (`only_if_changed=True`)**:
  - `ForeignKey` models now include `referenced_schema` and `ordinal_position` for composite and cross-schema foreign keys.
  - On the first rescan after upgrading, tables with foreign keys will be detected as changed once (`only_if_changed=True`) so the enriched FK metadata can be persisted.
- **Redis Stream Cleanup on Job Completion (`JobStore.ack`)**:
  - `JobStore.ack()` now invokes both `XACK` and `XDEL` on `scan:queue` to bound Redis Stream memory usage. Historical job auditing remains available via `scan:job:{id}` and `scan:jobs` sorted sets (with configurable TTL).
- **Strict Configuration File Validation**:
  - Passing an explicit `config_file` (`irides -c <path>` or `Catalog(config_file=...)`) that does not exist or has invalid YAML/JSON syntax now raises `FileNotFoundError` / `ValueError` immediately instead of silently returning an empty target list.
- **Async Scan HTTP Status Code**:
  - `POST /api/v1/scan` returns HTTP `202 Accepted` (previously `200 OK`).
- **Strict Multi-Target Metadata Disambiguation (HTTP 409)**:
  - `GET /api/v1/metadata/{instance}/{database}/{table}` and `PATCH /api/v1/metadata/{instance}/{database}/{table}` now return HTTP `409 Conflict` when the same `instance/database/table` exists under multiple distinct `config_name` targets and `?config_name=` is omitted. Pass `?config_name=<target>` (or select a target in `/ui`) to disambiguate.
- **DuckDB Schema-Level Metadata & Minimum Version**:
  - `DuckDBConnector` now uses the actual DuckDB schema name (`main`, custom schemas) as `schema_name` instead of the file path, and requires `duckdb>=1.1.0`.
