# irides

Portable, Git-ready database introspection and documentation for developers, data teams, and AI agents.

`irides` inspects SQL, NoSQL, and analytical databases, normalizes their structure into canonical Pydantic models, preserves human curation (`owner`, `notes`, `classification`, `tags`) across schema refreshes, and exports deterministic **Markdown** and **Open Knowledge Format (OKF v0.2)** catalogs.

---

## Quickstart in 60 Seconds (SQLite, No Docker or Redis Required)

You can use `irides` locally from the CLI or Python without starting Redis, Docker, or the web API.

### 1. Install Core + CLI

```bash
pip install -e ./core -e ./cli
```

*(Optional extras for external engines: `pip install -e "./core[postgres,mysql,duckdb,mongo,aws,trino,ai]"`)*

### 2. Create and Introspect a Local SQLite Database

```bash
python examples/sqlite_demo/setup_demo.py
irides -c examples/sqlite_demo/irides.yaml describe --target demo_sqlite
```

This generates:
- Canonical JSON metadata in `storage/metadata/demo_sqlite/...`
- Standalone Markdown files in `storage/exports/markdown/demo_sqlite/...`
- An OKF v0.2 bundle in `storage/exports/okf/catalog/` with an `index.md` catalog index.

### 3. Add Human Governance & Notes (Preserved Across Re-Scans)

```bash
irides metadata update ./demo.sqlite main orders \
  '{"owner":"checkout-team","classification":"confidential","tags":["orders","core"],"notes":"Primary order ledger table."}' \
  --target demo_sqlite
```

Re-running `irides -c examples/sqlite_demo/irides.yaml describe --target demo_sqlite --only-if-changed` keeps your `owner`, `classification`, `tags`, and `notes` intact and updates the Markdown/OKF exports:

```markdown
# main.orders

## Source

- Configuration: `demo_sqlite`
- Instance: `./demo.sqlite`
- Schema: `main`
- Table: `orders`
- Metadata updated: `2026-04-20T00:00:00+00:00`

## Governance

- Owner: `checkout-team`
- Classification: `confidential`
- Tags: `orders`, `core`

## Notes

Primary order ledger table.

## Columns

| Name | Type | Nullable | Description |
| --- | --- | --- | --- |
| id | INTEGER | False |  |
| customer_id | INTEGER | False |  |
| order_number | TEXT | False |  |
| total_cents | INTEGER | False |  |
| currency | TEXT | False |  |
| placed_at | TEXT | False |  |

## Keys and Relationships

- Primary key: `id`
- `customer_id` -> `customers.id`

## Indexes

- `sqlite_autoindex_orders_1`: unique `order_number`
```

Pass `--no-preformat` to `irides describe` (or `irides metadata export --no-preformat`) to include the `Default` column and non-unique secondary indexes in the exported Markdown/OKF documents.

---

## Python Library Usage (`irides_core`)

Use the high-level `Catalog` facade when embedding Irides in Python scripts, CI pipelines, or custom agents:

```python
from irides_core import Catalog

catalog = Catalog(config_file="examples/sqlite_demo/irides.yaml")

for inst in catalog.instances("demo_sqlite"):
    print("Instance:", inst.name)

outcomes = catalog.describe(
    config_name="demo_sqlite",
    schema_name="main",
    table_name="orders",
    only_if_changed=True,
)
for item in outcomes:
    print(item.table.table_name, [col.name for col in item.table.columns])
```

---

## Linking Repositories to the Catalog (`database.md`)

Projects can declare which database resources they read or write using a versioned `database.md` frontmatter (or YAML/JSON manifest) and validate it against the Irides Metadata Store:

```bash
irides manifest validate examples/sqlite_demo/database.md
irides manifest links examples/sqlite_demo/database.md
```

---

## Overview

When building AI agents or data tools across multiple databases, a primary challenge is providing accurate, low-overhead schema context. Without proper grounding, LLMs frequently hallucinate column names, infer non-existent relationships, or generate invalid SQL/NoSQL queries.

`irides` acts as a **context provider layer** that:
- Introspects diverse SQL, NoSQL, and cloud analytics databases.
- Normalizes schemas, tables, columns, indexes, and primary/foreign keys into structured Pydantic models.
- Provides a local CLI (`irides`), a Python SDK (`irides_core`), a versioned REST API (`/api/v1`), MCP endpoints, and asynchronous table scanning via **Redis Streams**.
- Generates multi-format documentation artifacts, including standalone **Markdown** and **Open Knowledge Format (OKF v0.2)** catalog bundles with deterministic essential views.
- Optionally generates semantic table documentation via **LiteLLM** and stores it separately from raw schema metadata.
- Optimizes payload size for LLMs using lightweight serialization ([TOON](https://github.com/toon-format/toon)).
- Persists introspected metadata (with human annotations) in a **Metadata Store** backed by JSON files (with S3/Athena interfaces planned).

---

## Architecture Overview

The system is split into microservices connected via Docker networks and Redis Streams:

```
┌─────────────────────┐     ┌──────────────────────┐
│   MCP Client / LLM  │     │  Browser (Web UI /ui) │
└──────────┬──────────┘     └──────────┬────────────┘
           │ HTTP / TOON               │ HTTP
           ▼                           ▼
    ┌─────────────┐       ┌────────────────────────────────┐
    │  MCP Server │──────►│           FastAPI               │
    └─────────────┘ HTTP  │  REST API (/api/v1)             │
                          │  Metadata API (/api/v1/metadata)│
                          └────────┬───────────┬────────────┘
                                   │           │ read/write
                                   ▼           ▼
                          ┌──────────────┐  ┌──────────────────────┐
                          │ Redis Stream │  │   Metadata Store      │
                          │ (scan:queue) │  │ (JSON / S3 / Athena)  │
                          └──────┬───────┘  └──────────┬───────────┘
                                 │                     │ derived
                                 ▼                     ▼ exports
                          ┌─────────────┐   ┌──────────────────────┐
                          │   Worker    │──►│   Artifact Store     │
                          │  (Consumer) │   │  (Markdown & OKF)    │
                          └──────┬──────┘   └──────────────────────┘
                                 │
                          ┌──────┴──────┐
                                 │
                       ┌─────────┴──────────┐
                       │    Core Library     │
                       └────────────────────┘
                                 │
           ┌─────────────────────┼──────────────────────┐
           ▼                     ▼                      ▼
    ┌──────────────┐   ┌──────────────────┐   ┌──────────────┐
    │ MySQL / PG   │   │ Dynamo / Mongo   │   │ Athena/Trino │
    └──────────────┘   └──────────────────┘   └──────────────┘
```

- **`core/`**: Shared Python library (`irides_core` / `core.db_connector`) providing the `Catalog` facade, connector abstractions, models, optional Redis caching, configuration loaders, multi-format export engines (Markdown & OKF), manifest validator, and Redis `JobStore`.
- **`cli/`**: Command-line interface (`irides`) for local introspection, metadata management, offline export regeneration, and manifest validation.
- **`infra/`**: Shared Redis container and `multi-db-net` Docker network.
- **`api/`**: FastAPI web service exposing the versioned REST API, Metadata API, and Web UI (`/ui`).
- **`worker/`**: Async task consumer executing background scans, writing metadata and generating derived export artifacts.
- **`mcp/`**: FastMCP server exposing introspection, metadata, and scan tools directly to AI assistants.

---

## REST API (`/api/v1`)

All API endpoints are served under the `/api/v1` prefix.

### Core Endpoints

| Method | Path | Body / Query Parameters | Description |
|---|---|---|---|
| `GET` | `/api/v1/configurations` | — | List all active database configurations |
| `POST` | `/api/v1/connect` | `config_name` | Test database connection |
| `POST` | `/api/v1/instances` | `config_name?` | List instances; omit `config_name` to list all |
| `POST` | `/api/v1/schemas` | `config_name?`, `instance_name?` | List databases/schemas |
| `POST` | `/api/v1/tables` | `config_name?`, `instance_name?`, `schema_name?`, `limit?`, `offset?` | List tables |
| `POST` | `/api/v1/describe` | `config_name?`, `instance_name?`, `schema_name?`, `table_name?`, `generate_ai_docs?`, `save_metadata?`, `only_if_changed?`, `export_options?` | Describe table structure and optional AI documentation |
| `POST` | `/api/v1/scan` | `config_name?`, `instance_name?`, `schema_name?`, `generate_ai_docs?`, `save_metadata?`, `only_if_changed?`, `export_options?` | Enqueue async scan job — returns `job_id` (HTTP 202) |
| `GET` | `/api/v1/scan/{job_id}` | `include_results?` | Get scan job status and optional results |
| `GET` | `/api/v1/scans` | `limit?` | List recent scan jobs (newest first) |

Scope fields are all optional — omitting any field expands the operation to all available values at that level. Send header `no-cache: true` to bypass the Redis introspection cache.

### Multi-Format Artifact Exports (Markdown & OKF)

Both `/describe` and `/scan` generate derived documentation artifacts by default alongside canonical JSON metadata:
- **Markdown**: Clean, human- and LLM-readable Markdown documentation rendering schema columns, descriptions, primary keys, foreign keys, unique indexes, and partition layouts.
- **Open Knowledge Format (OKF v0.2)**: Structured concept documents with YAML frontmatter (`type: Database Table`, title, description, tags, generator metadata, identifiers) and Markdown body, with an automatically maintained `index.md` catalog bundle index.
- **Deterministic Preformatting (`essential_record`)**: Enabled by default (`preformat: true`), compacting tables to essential structural and semantic elements while omitting secondary non-unique indexes and internal metadata to minimize LLM context overhead.
- **Decoupled Persistence**: Exports run independently of canonical metadata storage — setting `save_metadata: false` allows generating Markdown or OKF artifacts without saving JSON files.

Files are organized under `STORAGE_METADATA_DIR` and `STORAGE_EXPORT_DIR`:

```text
storage/
  metadata/
    {config}/{instance}/{schema}/{table}.json
  exports/
    markdown/
      {config}/{instance}/{schema}/{table}.md
    okf/
      catalog/
        index.md
        {config}/{instance}/{schema}/{table}.md
```

---

## Metadata API (`/api/v1/metadata`)

The Metadata API reads from and writes to the **Metadata Store** — a persistent store of previously introspected table schemas that may also carry human-authored annotations (owner, tags, notes, etc.). Data in this store is independent of live database connectivity; results reflect the last time a table was scanned.

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/metadata` | List all stored instances (paginated) |
| `GET` | `/api/v1/metadata/{instance}` | List stored databases for an instance |
| `GET` | `/api/v1/metadata/{instance}/{database}` | List stored tables for a database |
| `GET` | `/api/v1/metadata/{instance}/{database}/{table}` | Get full stored metadata JSON for a table |
| `PATCH` | `/api/v1/metadata/{instance}/{database}/{table}` | Merge custom fields into a table's metadata document |

### Pagination

`GET /api/v1/metadata` accepts optional query parameters:

| Parameter | Default | Description |
|---|---|---|
| `page` | `1` | Page number (1-indexed) |
| `page_size` | `50` | Results per page |

### Custom Fields (PATCH)

`PATCH /api/v1/metadata/{instance}/{database}/{table}` accepts a JSON body with arbitrary key/value pairs to merge into the stored document. This allows attaching human annotations — owner, team, tags, notes, data classification, SLA, and so on — without overwriting existing schema fields.

The following fields are **protected** and cannot be overwritten via PATCH:

- `metadata_key`
- `config_name`
- `instance_name`
- `schema_name`
- `table_name`
- `updated_at`

Example request body:

```json
{
  "owner": "data-platform-team",
  "tags": ["pii", "gdpr"],
  "notes": "Replicated from production every 6 hours.",
  "data_classification": "confidential"
}
```

### Custom Field Preservation

`save_table_metadata` preserves any custom fields already present in the stored document whenever a table is re-described or re-scanned. Human annotations are never silently overwritten by automated introspection runs.

Pass `only_if_changed=true` on a describe or scan request to skip writing to the Metadata Store when the freshly introspected schema is identical to the stored one. This avoids resetting `updated_at` and is the default mode used by the Web UI's single-table refresh action.

---

## Web UI (`/ui`)

A browser-based interface is available at `GET /ui`. It connects to the same FastAPI service as the REST and Metadata APIs — no separate deployment is needed.

### Features

- **Browse**: Navigate the instance / database / table hierarchy stored in the Metadata Store.
- **Filter loaded items**: Client-side filtering across loaded instance, database, and table lists.
- **Inspect**: View the full metadata JSON for any table with syntax highlighting.
- **Annotate**: Edit and save custom fields (owner, tags, notes, etc.) directly from the browser via the PATCH Metadata API.
- **Theme toggle**: Seamless switch between Dark and Light mode with theme preferences persisted in `localStorage`.
- **Export controls**: Opt-out checkboxes for Markdown export, OKF bundle export, and Essential preformatting directly in table refresh and scan modals.
- **Scan**: Trigger an asynchronous scan at the instance or database level using the async scan API; a progress indicator shows job status.
- **Refresh**: Re-introspect a single table's schema from the live database (`only_if_changed=true` is applied so unchanged schemas do not overwrite existing annotations) and automatically regenerate derived exports.

---

## Supported Database Connectors & Capabilities Matrix

| Database | Connector Type | Extra | Primary Keys | Foreign Keys | Indexes | Partitions | Notes & Limitations |
|---|---|---|---|---|---|---|---|
| **SQLite** | `sqlite` | *(built-in)* | Yes (`PRAGMA table_info`) | Yes (`PRAGMA foreign_key_list`, composite ordinal order) | Yes (`PRAGMA index_list` / `index_info`) | No | Opens existing files in read-only mode (`mode=ro`); schema is `main`. |
| **PostgreSQL** | `postgres` | `postgres` | Yes (`table_constraints`) | Yes (composite-safe via `position_in_unique_constraint`, cross-schema aware) | Yes (`pg_indexes`) | Yes (`pg_inherits`) | Connects to configured `DATABASE` (default `postgres`). |
| **MySQL / MariaDB** | `mysql` | `mysql` | Yes (`KEY_COLUMN_USAGE`) | Yes (`KEY_COLUMN_USAGE`) | Yes (`STATISTICS`) | Yes (`PARTITIONS`) | Supports single `HOST` or multi-host configurations. |
| **DuckDB** | `duckdb` | `duckdb` | Yes (`duckdb_constraints`) | Yes (`duckdb_constraints`, composite positional pairing) | Yes (`duckdb_indexes`) | No | File databases opened with `read_only=True`; `:memory:` opened read-write. |
| **MongoDB** | `mongodb` | `mongo` | `_id` inferred | No | Yes (`index_information`) | No | Schema inferred by sampling up to 100 documents per collection. |
| **Amazon DynamoDB** | `dynamodb` | `aws` | Yes (`KeySchema` HASH/RANGE) | No | Yes (`GlobalSecondaryIndexes` & `LocalSecondaryIndexes` preserved in exports) | No | Only declared key attributes are returned by `DescribeTable`; GSI/LSI attributes are nullable. |
| **Amazon Athena** | `athena` | `aws` | No | No | No | Yes (`PartitionKeys` via Glue) | Uses AWS Glue Data Catalog (`get_databases` / `get_tables`). |
| **Trino / Presto** | `trino` / `presto` | `trino` | Best-effort | No | No | No | Instances represent catalogs (`SHOW CATALOGS`); column metadata via `DESCRIBE`. |

---

## DB Configuration & Activation

### Manage Targets & `.env` Variables via CLI

You can configure database targets and runtime environment variables directly from the CLI without manually editing YAML or `.env` files:

```bash
# Save a PostgreSQL target to irides.yaml with password stored in .env (${DB_TARGET_ANALYTICS_PG_PASSWORD})
irides config set-target analytics_pg \
  --type postgres \
  --host pg-analytics.internal \
  --user reader \
  --password secret \
  --database warehouse

# Or save a target purely as DB_TARGET_* variables in .env
irides config set-target local_sqlite --type sqlite --database ./demo.sqlite --format env

# Set / inspect / remove supported runtime env vars in .env
irides config set-env LITELLM_MODEL gpt-4o
irides config list-env
irides config show
irides config remove-target analytics_pg
```

Configurations are dynamically activated based on `DB_TARGETS`, which supports any number of named targets for any connector.

### Generic Multi-Target Format

Use `DB_TARGETS` to list named database targets. Each target name maps to `DB_TARGET_<TARGET_KEY>_*` variables, where `<TARGET_KEY>` is the uppercased target name with non-alphanumeric characters replaced by underscores.

```env
DB_TARGETS=sales_mysql,billing_mysql,analytics_pg

DB_TARGET_SALES_MYSQL_TYPE=mysql
DB_TARGET_SALES_MYSQL_HOST=mysql-sales.internal
DB_TARGET_SALES_MYSQL_USER=reader
DB_TARGET_SALES_MYSQL_PASSWORD=...
DB_TARGET_SALES_MYSQL_PORT=3306

DB_TARGET_BILLING_MYSQL_TYPE=mysql
DB_TARGET_BILLING_MYSQL_HOST=mysql-billing.internal
DB_TARGET_BILLING_MYSQL_USER=reader
DB_TARGET_BILLING_MYSQL_PASSWORD=...

DB_TARGET_ANALYTICS_PG_TYPE=postgres
DB_TARGET_ANALYTICS_PG_HOST=pg-analytics.internal
DB_TARGET_ANALYTICS_PG_USER=reader
DB_TARGET_ANALYTICS_PG_PASSWORD=...
DB_TARGET_ANALYTICS_PG_DATABASE=warehouse
```

Each target becomes its own `config_name` (`sales_mysql`, `billing_mysql`, `analytics_pg`) in API/MCP calls.

Supported `TYPE` values: `mysql`, `postgres`, `athena`, `dynamodb`, `mongodb`, `trino`, `presto`, `sqlite`, `duckdb`.

Common target variables:

| Type | Required Target Variables | Optional Target Variables |
|---|---|---|
| `mysql` | `TYPE`, `HOST` | `USER`, `PASSWORD`, `PORT`, `POOL_SIZE` |
| `postgres` | `TYPE`, `HOST` | `USER`, `PASSWORD`, `DATABASE`/`DB`, `PORT`, `POOL_SIZE` |
| `mongodb` | `TYPE`, `HOST` | `USER`/`USERNAME`, `PASSWORD`, `PORT`, `AUTH_SOURCE`, `TLS`, `TLS_ALLOW_INVALID` |
| `trino` / `presto` | `TYPE`, `HOST` | `USER`, `PASSWORD`, `PORT`, `HTTP_SCHEME`, `SESSION_PROPERTIES` |
| `athena` | `TYPE`, `REGION` | `CATALOG`, `S3_OUTPUT`, AWS credential variables |
| `dynamodb` | `TYPE`, `REGION` | `ENDPOINT_URL`, AWS credential variables |
| `sqlite` | `TYPE`, `DATABASE` | — |
| `duckdb` | `TYPE` | `DATABASE` |

AWS target credentials can be set per target (`DB_TARGET_<KEY>_AWS_ACCESS_KEY_ID`, etc.) or inherited from global `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`.

For Kubernetes deployments, put `DB_TARGETS` and all `DB_TARGET_*` variables in a shared Secret/ConfigMap and inject the same values into both API and Worker. MCP only needs `API_BASE_URL`; Redis does not need database credentials.

#### Exact Target Keys by Connector

In the examples below, replace `<KEY>` with the normalized target key. For a target named `sales_mysql`, `<KEY>` is `SALES_MYSQL`.

**MySQL / MariaDB**

```env
DB_TARGET_<KEY>_TYPE=mysql
DB_TARGET_<KEY>_HOST=                       # required
DB_TARGET_<KEY>_USER=root                   # optional, default root
DB_TARGET_<KEY>_PASSWORD=                   # optional, default empty
DB_TARGET_<KEY>_PORT=3306                   # optional, default 3306
DB_TARGET_<KEY>_POOL_SIZE=5                 # optional, default 5
```

**PostgreSQL**

```env
DB_TARGET_<KEY>_TYPE=postgres
DB_TARGET_<KEY>_HOST=                       # required
DB_TARGET_<KEY>_PORT=5432                   # optional, default 5432
DB_TARGET_<KEY>_USER=postgres               # optional, default postgres
DB_TARGET_<KEY>_PASSWORD=                   # optional, default empty
DB_TARGET_<KEY>_DATABASE=postgres           # optional, default postgres
DB_TARGET_<KEY>_DB=postgres                 # optional alias for DATABASE
DB_TARGET_<KEY>_POOL_SIZE=5                 # optional, default 5
```

**MongoDB**

```env
DB_TARGET_<KEY>_TYPE=mongodb
DB_TARGET_<KEY>_HOST=                       # required; hostname or mongodb:// URI
DB_TARGET_<KEY>_PORT=27017                  # optional, ignored when HOST is a URI
DB_TARGET_<KEY>_USER=                       # optional
DB_TARGET_<KEY>_USERNAME=                   # optional alias for USER
DB_TARGET_<KEY>_PASSWORD=                   # optional
DB_TARGET_<KEY>_AUTH_SOURCE=admin           # optional, default admin
DB_TARGET_<KEY>_TLS=false                   # optional, true/false
DB_TARGET_<KEY>_TLS_ALLOW_INVALID=false     # optional, true/false
```

**Trino / Presto**

```env
DB_TARGET_<KEY>_TYPE=trino                  # or presto
DB_TARGET_<KEY>_HOST=                       # required
DB_TARGET_<KEY>_PORT=8080                   # optional, default 8080
DB_TARGET_<KEY>_USER=trino                  # optional, default trino or presto
DB_TARGET_<KEY>_PASSWORD=                   # optional
DB_TARGET_<KEY>_HTTP_SCHEME=http            # optional, http or https
DB_TARGET_<KEY>_SESSION_PROPERTIES={}       # optional JSON object
```

**Amazon Athena**

```env
DB_TARGET_<KEY>_TYPE=athena
DB_TARGET_<KEY>_REGION=                     # required
DB_TARGET_<KEY>_CATALOG=AwsDataCatalog      # optional
DB_TARGET_<KEY>_S3_OUTPUT=                  # optional for metadata operations
DB_TARGET_<KEY>_AWS_ACCESS_KEY_ID=          # optional; falls back to global AWS env/IAM
DB_TARGET_<KEY>_AWS_SECRET_ACCESS_KEY=      # optional; falls back to global AWS env/IAM
DB_TARGET_<KEY>_AWS_SESSION_TOKEN=          # optional; falls back to global AWS env/IAM
```

**Amazon DynamoDB**

```env
DB_TARGET_<KEY>_TYPE=dynamodb
DB_TARGET_<KEY>_REGION=                     # required
DB_TARGET_<KEY>_ENDPOINT_URL=               # optional, useful for local DynamoDB
DB_TARGET_<KEY>_AWS_ACCESS_KEY_ID=          # optional; falls back to global AWS env/IAM
DB_TARGET_<KEY>_AWS_SECRET_ACCESS_KEY=      # optional; falls back to global AWS env/IAM
DB_TARGET_<KEY>_AWS_SESSION_TOKEN=          # optional; falls back to global AWS env/IAM
```

**SQLite**

```env
DB_TARGET_<KEY>_TYPE=sqlite
DB_TARGET_<KEY>_DATABASE=                   # required path to .sqlite/.db file
```

**DuckDB**

```env
DB_TARGET_<KEY>_TYPE=duckdb
DB_TARGET_<KEY>_DATABASE=:memory:           # optional, default :memory:
```

Empty optional variables are treated as unset, so connector defaults still apply where defined. `DB_CONFIG_FILE` can point to an explicit `.env` file for Docker containers, e.g. `/app/api/.env`.

### Optional AI Documentation & Storage Settings

Set `generate_ai_docs=true` on `/describe` or `/scan` requests to generate `ai_documentation` via LiteLLM. Results include:
- `ai_documentation`: generated summary and column descriptions, or `null` if generation fails.
- `ai_generation_status`: `generated` or `failed`.
- `ai_generation_error`: provider/import/network error detail when generation fails.

Relevant environment variables:

| Variable | Default | Description |
|---|---|---|
| `LITELLM_MODEL` | `gpt-4o-mini` | LiteLLM model name |
| `LITELLM_API_KEY` | *(none)* | Optional provider API key override |
| `LITELLM_API_BASE` | *(none)* | Optional custom LiteLLM API base URL |
| `STORAGE_METADATA_DIR` | `storage/metadata` | File metadata JSON output directory |
| `STORAGE_EXPORT_DIR` | `storage/exports` | Directory for generated Markdown and OKF exports |
| `METADATA_STORE_TYPE` | `file` | Metadata store backend (`file`; `s3`/`athena` planned) |

---

## Quick Start with Docker Compose

1. **Start Shared Infrastructure (Redis)**:
   ```bash
   docker compose -f infra/docker-compose.infra.yml up -d
   ```

2. **Start API and Worker Services**:
   ```bash
   docker compose -f api/docker-compose.yml up -d
   docker compose -f worker/docker-compose.yml up -d
   ```

3. **Or Start Full MCP Pipeline**:
   ```bash
   docker compose -f mcp/docker-compose.yml up -d
   ```

Once the API service is running, the Web UI is available at `http://localhost:<port>/ui` and the REST API is available at `http://localhost:<port>/api/v1`.

---

## Security & Deployment Guidelines

- **Database Least Privilege**: Always configure `irides` targets with read-only database credentials restricted to schema/catalog metadata.
- **API Authentication**: Set `IRIDES_API_KEY` on the FastAPI service (and MCP client) to require an `X-API-Key` header (or `Authorization: Bearer <key>`) on all `/api/v1` endpoints. The Web UI (`/ui`) includes a built-in API Key selector stored in `localStorage` (`irides_api_key`) and automatically prompts for the key when the server returns HTTP 401.
- **Untrusted Metadata & LLMs**: When `generate_ai_docs=true` is enabled, table/column names and database comments are sent to the configured `LITELLM_MODEL`. Database comments are wrapped as untrusted data in the prompt, and only validated `summary` and `column_descriptions` fields are accepted.

---

## Python Core Usage Example

```python
from irides_core import Catalog
from irides_core.exporting import ExportOptions

# 1. Initialize Catalog (uses NullCacheManager by default; no Redis required)
catalog = Catalog(config_file="examples/sqlite_demo/irides.yaml")

# 2. List active database instances for a named target
instances = catalog.instances("demo_sqlite")
for inst in instances:
    print(f"Found instance: {inst.name}")

# 3. Describe tables and persist metadata + Markdown/OKF exports
outcomes = catalog.describe(
    config_name="demo_sqlite",
    instance_name=instances[0].name,
    schema_name="main",
    save_metadata=True,
    only_if_changed=True,
    export_options=ExportOptions(),
)
for outcome in outcomes:
    table_desc = outcome.table
    pk_columns = table_desc.primary_key.column_names if table_desc.primary_key else []
    for col in table_desc.columns:
        print(f"{col.name}: {col.data_type} (PK={col.name in pk_columns})")
```

---

## Status & Roadmap

- **Status**: Active Alpha
- **Features**:
  - [x] Redis Stream async scanner & dead worker consumer recovery
  - [x] TOON format output for LLM context reduction
  - [x] MCP Server integration for Claude / Gemini / Cursor
  - [x] Multi-format artifact export (Markdown & Open Knowledge Format - OKF v0.2) with essential preformatting
  - [x] Unified host and flat instance resolution
  - [x] Automatic semantic documentation & LLM-generated table descriptions (via LiteLLM)
  - [x] Abstract metadata storage (`FileMetadataStore` JSON persistence & DB provider interface)
  - [x] Versioned REST API (`/api/v1`)
  - [x] Metadata Store read/write API with pagination and human annotations
  - [x] Web UI for metadata browsing and editing (`/ui`) with dark/light themes
  - [x] `only_if_changed` flag on describe/scan to avoid overwriting unchanged schemas
  - [x] Custom field preservation across re-describes
