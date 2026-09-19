# API

FastAPI service exposing database introspection over HTTP. Provides synchronous point-in-time endpoints, async scan job enqueueing, stored metadata read/write, and a browser UI. Depends only on **core**.

All routes are versioned under `/api/v1`.

---

## Endpoints

### Synchronous Introspection

| Method | Path | Body Parameters | Description |
|---|---|---|---|
| `GET` | `/api/v1/configurations` | — | List all currently active database configurations |
| `POST` | `/api/v1/connect` | `config_name` | Test database connection |
| `POST` | `/api/v1/instances` | `config_name?` | List database instances. Omit `config_name` to list all active configurations |
| `POST` | `/api/v1/schemas` | `config_name?`, `instance_name?` | List schemas/databases. Omitted fields expand the scope |
| `POST` | `/api/v1/tables` | `config_name?`, `instance_name?`, `schema_name?`, `limit?`, `offset?` | List tables. Omitted scope fields expand the query |
| `POST` | `/api/v1/describe` | `config_name?`, `instance_name?`, `schema_name?`, `table_name?`, `generate_ai_docs?`, `save_metadata?`, `only_if_changed?`, `export_options?` | Describe table structure and optional AI documentation |

- **Bypass Redis Cache**: Send header `no-cache: true`.
- **TOON Payload Format**: Send header `Accept: application/toon` for LLM token reduction.
- **AI Documentation**: Send `generate_ai_docs: true` to include `ai_documentation`, `ai_generation_status`, and `ai_generation_error` in described tables. If `save_metadata: true`, the same AI documentation is persisted in metadata storage.
- **`only_if_changed`**: When `save_metadata: true`, skips writing the metadata file if `schema_description` is identical to the stored version. Preserves `updated_at` and human annotations unchanged. Defaults to `false`.
- **Export Options (`export_options`)**: Controls generation of derived artifacts (`formats`: `["markdown", "okf"]`, `preformat: true` by default). Exports are decoupled from JSON persistence, meaning exports are created even when `save_metadata: false`. Legacy requests containing `save_markdown` are automatically migrated.

### Async Table Scan Jobs

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/scan` | Enqueue an async scan job — returns `job_id` immediately (HTTP 202 Accepted) |
| `GET` | `/api/v1/scan/{job_id}` | Retrieve job status; add `?include_results=true` for full `TableDescription` list |
| `GET` | `/api/v1/scans?limit=50` | List recent scan jobs (newest first, lightweight metadata) |

Scan status values are `pending`, `running`, `completed`, `partial`, and `failed`.

Scan scope & options (all optional):
```json
{
  "config_name": "sales_mysql",
  "instance_name": "db1.company.com",
  "schema_name": "production",
  "generate_ai_docs": true,
  "save_metadata": true,
  "only_if_changed": false,
  "export_options": {
    "formats": ["markdown", "okf"],
    "preformat": true
  }
}
```

- **Target Resolution**: If `instance_name` is provided without `config_name`, the API automatically resolves the target configuration. Requests with instances not matching any configured target are rejected with `HTTP 400 Bad Request`.

### Metadata Store API

Read and update stored metadata snapshots. These are the JSON documents written by `/describe` and scan jobs; they may also contain human-added fields (owner, tags, notes, etc.).

| Method | Path | Query Parameters | Description |
|---|---|---|---|
| `GET` | `/api/v1/metadata` | `page?`, `page_size?` | List all stored instances (paginated) |
| `GET` | `/api/v1/metadata/{instance}` | `page?`, `page_size?` | List stored databases for an instance |
| `GET` | `/api/v1/metadata/{instance}/{database}` | `page?`, `page_size?` | List stored tables for an instance+database |
| `GET` | `/api/v1/metadata/{instance}/{database}/{table}` | — | Get full stored metadata JSON for a table |
| `PATCH` | `/api/v1/metadata/{instance}/{database}/{table}` | — | Merge custom fields into the stored document |

All list endpoints return a paginated envelope:
```json
{
  "items": ["instance_a", "instance_b"],
  "total": 2,
  "page": 1,
  "page_size": 20,
  "pages": 1
}
```

The PATCH endpoint accepts any JSON object. Fields that are protected system keys (`metadata_key`, `config_name`, `instance_name`, `schema_name`, `table_name`, `updated_at`) are silently ignored; all other fields (including `schema_description`, `ai_documentation`, `owner`, `tags`, `notes`, custom fields) are merged in. Returns `404` if the table has no stored metadata yet, `422` if the payload is empty.

Example — add an owner and tags to a table:
```bash
curl -X PATCH http://localhost:8000/api/v1/metadata/db1.company.com/sales/orders \
  -H "Content-Type: application/json" \
  -d '{"owner": "data-team", "tags": ["billing", "critical"]}'
```

### Web UI

A browser-based interface is available at `GET /ui`. It provides:

- Three-panel sidebar: **Instances → Databases → Tables** with search/filter
- Table metadata viewer with JSON syntax highlighting
- Inline editor for custom fields (Edit / Save / Cancel)
- **Theme support**: Dark and Light mode toggle, persisted in `localStorage` with stylesheets served via `/static`
- **Export options**: Opt-out checkboxes for `Export Markdown`, `Export OKF`, and `Essential` preformatting directly in the table refresh panel and the scan modal
- **Scan** button at instance and database level to trigger async background scans with live status polling and export settings
- **Refresh schema** button at table level to refresh the live schema (`only_if_changed: true`) and re-export artifacts without overwriting human annotations

---

## Environment Variables

Copy `.env.example` to `.env`.

| Variable | Default | Description |
|---|---|---|
| `REDIS_HOST` | `localhost` | Redis host (must match Worker) |
| `REDIS_PORT` | `6379` | Redis port |
| `REDIS_DB` | `0` | Redis database index |
| `REDIS_TTL_SECONDS` | `86400` | Introspection cache TTL (1 day) |
| `CACHE_KEY_PREFIX` | `irides` | Redis key prefix (must match Worker) |
| `DB_CONFIG_FILE` | *(none)* | Optional explicit path to `.env` file for Docker container |
| `DB_TARGETS` | *(none)* | Comma-separated list of named DB targets |
| `SCAN_RESULTS_TTL_SECONDS` | `604800` | Scan job/result retention in Redis (7 days) |
| `STORAGE_METADATA_DIR` | `storage/metadata` | Metadata JSON output directory |
| `STORAGE_EXPORT_DIR` | `storage/exports` | Directory for generated Markdown and OKF exports |
| `METADATA_STORE_TYPE` | `file` | Metadata store backend (`file`; `s3`/`athena` planned) |
| `LITELLM_MODEL` | `gpt-4o-mini` | LLM model for AI doc generation |
| `LITELLM_API_KEY` | *(none)* | Optional LiteLLM API key override |
| `LITELLM_API_BASE` | *(none)* | Optional LiteLLM API base URL |

DB target variables — see [root README](../README.md#db-configuration--activation).

---

## Running

### Docker Compose

```bash
# Start shared Redis first
docker compose -f ../infra/docker-compose.infra.yml up -d

# Start API
docker compose up -d
```

### Local Development

```bash
pip install -r requirements.txt
uvicorn api.irides_api.main:app --host 0.0.0.0 --port 8000 --reload
```

The interactive docs are at `http://localhost:8000/docs` and the UI at `http://localhost:8000/ui`.
